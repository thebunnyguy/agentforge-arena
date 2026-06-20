"""Deterministic single-run scoring (framework §1).

S = G · T_hidden · (0.85 + 0.15·Q)

G          product of the five hard gates, in {0, 1}
T_hidden   weighted fraction of hidden tests passed, in [0, 1]
Q          bounded quality modifier, in [0, 1]
X          functional pass: G == 1 AND every hidden test passed

Quality can only move an already-earned correctness score within the band
[0.85, 1.0] of itself; it can never substitute for correctness.
"""

from __future__ import annotations

from .types import QualityInputs, RunInput, RunScore, RunStatus

# Default component weights for Q (framework §1). Must sum to 1.0.
QUALITY_WEIGHTS: dict[str, float] = {
    "lint": 0.20,
    "typecheck": 0.25,
    "static": 0.20,
    "security": 0.20,
    "parsimony": 0.15,
}


def _clamp01(x: float) -> float:
    """Clamp a value to the closed unit interval [0, 1]."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def compute_t_hidden(run: RunInput) -> float:
    """Weighted fraction of hidden tests passed.

    T_hidden = sum(w_j · passed_j) / sum(w_j) over the hidden suite, with
    default equal weights. If there are no hidden tests, return 0.0.
    Implements framework §1.
    """
    hidden = run.hidden
    if not hidden:
        return 0.0
    total_weight = 0.0
    passed_weight = 0.0
    for t in hidden:
        total_weight += t.weight
        if t.passed:
            passed_weight += t.weight
    # Degenerate: all weights zero (or sum to zero) -> no scorable signal.
    if total_weight <= 0.0:
        return 0.0
    return _clamp01(passed_weight / total_weight)


def baseline_adjusted_t_hidden(observed: float, snapshot_baseline: float) -> float:
    """Proposed baseline-relative hidden score, not used by ``score_run`` yet.

    Map snapshot-equivalent behavior to zero while preserving a full hidden pass
    at one: ``max(0, (observed - baseline) / (1 - baseline))``. Both inputs are
    clamped to [0, 1]. A baseline that already passes every hidden test is an
    invalid benchmark under the §8 task invariant and therefore returns zero.

    Wiring this into ``score_run`` would change stored continuous scores and
    requires a new formula version plus a recompute. The binary functional pass
    and Wilson leaderboard would not change, so v0.1 keeps the helper opt-in.
    """
    observed = _clamp01(observed)
    snapshot_baseline = _clamp01(snapshot_baseline)
    if snapshot_baseline >= 1.0:
        return 0.0
    return _clamp01(
        max(0.0, (observed - snapshot_baseline) / (1.0 - snapshot_baseline))
    )


def compute_quality(q: QualityInputs) -> tuple[float, dict[str, float]]:
    """Bounded quality modifier Q and the per-component values used.

    Compute each available component in [0, 1] (formulas in QualityInputs's
    docstring), drop unavailable (None) components, renormalise the remaining
    weights to sum to 1, and return the weighted mean. If EVERY component is
    unavailable, return (1.0, {}) — absent quality evidence must not penalise.
    Implements framework §1.
    """
    components: dict[str, float] = {}

    # lint: q_lint = max(0, 1 - lint_new_errors / 10)
    if q.lint_new_errors is not None:
        components["lint"] = _clamp01(1.0 - q.lint_new_errors / 10.0)

    # typecheck: q_type = 1.0 if typecheck_ok else 0.0
    if q.typecheck_ok is not None:
        components["typecheck"] = 1.0 if q.typecheck_ok else 0.0

    # static: q_static = clamp(1 - max(0, static_new_findings) / 10, 0, 1)
    if q.static_new_findings is not None:
        findings = max(0.0, q.static_new_findings)
        components["static"] = _clamp01(1.0 - findings / 10.0)

    # security: q_sec = max(0, 1 - security_new.weighted() / 3)
    if q.security_new is not None:
        components["security"] = _clamp01(1.0 - q.security_new.weighted() / 3.0)

    # parsimony: rho = lines_added / max(reference_lines, 10);
    #            q_pars = 1 if rho <= 2; (8 - rho)/6 if 2 < rho < 8; else 0.
    # Available only when BOTH lines_added and reference_lines are provided.
    if q.lines_added is not None and q.reference_lines is not None:
        rho = q.lines_added / max(q.reference_lines, 10)
        if rho <= 2.0:
            q_pars = 1.0
        elif rho < 8.0:
            q_pars = (8.0 - rho) / 6.0
        else:
            q_pars = 0.0
        components["parsimony"] = _clamp01(q_pars)

    # All unavailable -> absent evidence must not penalise.
    if not components:
        return 1.0, {}

    # Drop unavailable components, renormalise the remaining weights to sum 1.
    weight_sum = sum(QUALITY_WEIGHTS[name] for name in components)
    q_value = sum(
        QUALITY_WEIGHTS[name] * value for name, value in components.items()
    ) / weight_sum
    return _clamp01(q_value), components


def score_run(run: RunInput) -> RunScore:
    """Score one run end to end.

    - INFRA_FAILURE  -> voided RunScore (excluded from aggregation's n);
      final_score 0.0, functional_pass False, voided True.
    - Otherwise: G = run.gates.product(); T_hidden = compute_t_hidden(run);
      Q, components = compute_quality(run.quality);
      S = G * T_hidden * (0.85 + 0.15*Q);
      X = (G == 1) and len(run.hidden) > 0 and all(t.passed) and t_hidden > 0.

    The t_hidden > 0 clause keeps X consistent with S: a degenerate hidden suite
    whose weights sum to zero scores S = 0, so it must not register as a pass.
    Note a TIMEOUT naturally yields G = 0 via the no_timeout gate, hence S = 0.
    Implements framework §1.
    """
    if run.status is RunStatus.INFRA_FAILURE:
        return RunScore(
            status=run.status,
            gate_product=0,
            t_hidden=0.0,
            q=0.0,
            q_components={},
            final_score=0.0,
            functional_pass=False,
            voided=True,
        )

    gate_product = run.gates.product()
    t_hidden = compute_t_hidden(run)
    q_value, q_components = compute_quality(run.quality)
    multiplier = 0.85 + 0.15 * q_value
    final_score = gate_product * t_hidden * multiplier
    functional_pass = (
        gate_product == 1
        and len(run.hidden) > 0
        and all(t.passed for t in run.hidden)
        and t_hidden > 0.0
    )
    return RunScore(
        status=run.status,
        gate_product=gate_product,
        t_hidden=t_hidden,
        q=q_value,
        q_components=q_components,
        final_score=_clamp01(final_score),
        functional_pass=functional_pass,
        voided=False,
    )
