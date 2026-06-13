"""Shared type contract for the AgentForge Arena v0.1 evaluation kernel.

These dataclasses and enums are the stable interface every other module is
written against. Keep them frozen (scores are immutable facts, not mutable
state) and dependency-free (standard library only).

Specification: ../docs/EVALUATION_FRAMEWORK.md (sections 1, 2, 4, 6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #

class RunStatus(str, Enum):
    """Outcome class of a single run (framework §1, "Run status taxonomy").

    VALID         - executed and scorable; counts in n.
    TIMEOUT       - hit the wall-clock budget; counts in n as a failure (S=0).
    AGENT_ERROR   - agent crashed / produced no usable result; counts in n as
                    a failure (S=0).
    INFRA_FAILURE - the platform's fault (sandbox, mirror, host). VOIDED:
                    excluded from n, retried upstream, never scored against the
                    agent.
    """

    VALID = "valid"
    TIMEOUT = "timeout"
    AGENT_ERROR = "agent_error"
    INFRA_FAILURE = "infra_failure"


class Suite(str, Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    REGRESSION = "regression"


class TestStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIP = "skip"


# --------------------------------------------------------------------------- #
# Scoring inputs (framework §1)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Gates:
    """The five binary hard gates. G = product of all five, in {0, 1}.

    Any single failed gate forces G = 0 and therefore S = 0. Gates are binary
    and multiplicative (not weighted) because each represents a violation that
    makes the rest of the evidence meaningless.
    """

    setup_ok: bool
    diff_exists: bool
    scope_ok: bool
    regression_pass: bool
    no_timeout: bool

    def product(self) -> int:
        """G in {0, 1}: 1 iff every gate passed."""
        return int(
            self.setup_ok
            and self.diff_exists
            and self.scope_ok
            and self.regression_pass
            and self.no_timeout
        )


@dataclass(frozen=True)
class TestResult:
    """One hidden-suite test outcome, graded in the clean room.

    weight defaults to 1.0 (equal weighting); per-test weights come from the
    task's scoring recipe.
    """

    __test__ = False  # not a pytest test class despite the "Test" prefix

    name: str
    passed: bool
    weight: float = 1.0


@dataclass(frozen=True)
class SecurityFindings:
    """New security findings introduced by the diff, by severity.

    Severity weights (framework §1): high = 3, medium = 1, low = 0.25.
    """

    high: int = 0
    medium: int = 0
    low: int = 0

    def weighted(self) -> float:
        """V_new: the severity-weighted count of new findings."""
        return 3.0 * self.high + 1.0 * self.medium + 0.25 * self.low


@dataclass(frozen=True)
class QualityInputs:
    """Raw signals feeding the bounded quality modifier Q (framework §1).

    Every field may be None, meaning "this check was unavailable for this task"
    (e.g. no typechecker configured, no reference solution for parsimony). The
    scorer drops unavailable components and renormalises the remaining weights;
    if ALL are unavailable, Q := 1.0 (absent evidence must not penalise).

    Component formulas (each clamped to [0, 1]):
      lint       q_lint   = max(0, 1 - lint_new_errors / 10)
      typecheck  q_type   = 1.0 if typecheck_ok else 0.0
      static     q_static = clamp(1 - max(0, static_new_findings) / 10, 0, 1)
      security   q_sec    = max(0, 1 - security_new.weighted() / 3)
      parsimony  rho = lines_added / max(reference_lines, 10);
                 q_pars = 1 if rho <= 2; (8 - rho) / 6 if 2 < rho < 8; else 0
    Default component weights: lint .20, typecheck .25, static .20,
                               security .20, parsimony .15  (sum = 1.0).
    """

    lint_new_errors: int | None = None
    typecheck_ok: bool | None = None
    static_new_findings: float | None = None      # W_post - W_base; <=0 => no penalty
    security_new: SecurityFindings | None = None
    lines_added: int | None = None                # A, for parsimony
    reference_lines: int | None = None            # R, for parsimony; None => unavailable


@dataclass(frozen=True)
class RunInput:
    """Everything needed to deterministically score one run."""

    status: RunStatus
    gates: Gates
    hidden: tuple[TestResult, ...] = ()
    quality: QualityInputs = field(default_factory=QualityInputs)


@dataclass(frozen=True)
class RunScore:
    """The deterministic score of one run.

    S = G · T_hidden · (0.85 + 0.15·Q).  X (functional_pass) is True iff G == 1
    AND every hidden test passed. voided is True iff the run was an
    INFRA_FAILURE (excluded from aggregation's n).
    """

    status: RunStatus
    gate_product: int                    # G in {0, 1}
    t_hidden: float                      # T_hidden in [0, 1]
    q: float                             # Q in [0, 1]
    q_components: dict[str, float]       # per-component q values actually used
    final_score: float                   # S in [0, 1]
    functional_pass: bool                # X
    voided: bool                         # True for INFRA_FAILURE


# --------------------------------------------------------------------------- #
# Aggregation output (framework §2)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AggregateResult:
    """Aggregates over the VALID runs of one (agent, task) cell.

    n_valid excludes voided (INFRA_FAILURE) runs. pass_rate = n_pass / n_valid.
    All S-distribution stats are computed over the non-voided runs' S values.
    """

    n_valid: int
    n_pass: int
    pass_rate: float                     # p-hat = c / n
    wilson_low: float
    wilson_high: float
    mean_s: float
    median_s: float
    min_s: float
    max_s: float                         # cherry-picking hazard; diagnostic only
    std_s: float                         # Bessel-corrected (n-1)
    stability: float                     # max(0, 1 - 2·std_s)
    conservative_continuous: float       # max(0, mean - t_{.95,n-1}·s/sqrt(n))
    timeout_rate: float
    infra_void_rate: float               # v / (n_valid + v)
    reliability: float                   # frac of valid runs not TIMEOUT/AGENT_ERROR
    pass_at_k: dict[int, float]          # unbiased pass@k for k <= n_valid
    deterministic: bool                  # variance 0-by-construction (flagged)
    bimodal: bool                        # pass/fail clusters; mean is a fiction
    provisional: bool                    # n_valid < 5 -> excluded from rankings


# --------------------------------------------------------------------------- #
# Domain profiling (framework §4)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class TaskDomainContribution:
    """One task's contribution to a domain's pooled score.

    weight is the task's tag weight for this domain (1.0 primary, 0.5 secondary,
    0.25 tertiary). n / c are the task's valid-run and pass counts. std is the
    per-task Bessel std of S, used for run-mass-weighted domain stability.
    """

    weight: float                        # w_tk
    n: int                               # valid runs on this task
    c: int                               # passes on this task
    std: float = 0.0                     # per-task std of S


@dataclass(frozen=True)
class DomainScore:
    """Per-domain pooled capability with a Kish-effective-n Wilson interval.

    pooled_pass_rate = sum(w·c) / sum(w·n).
    n_eff (Kish)     = (sum(w·n))^2 / sum(w^2·n).
    displayable is True iff n_tasks >= 5 AND n_runs >= 25.
    """

    domain: str
    pooled_pass_rate: float
    n_eff: float
    wilson_low: float
    wilson_high: float
    stability: float
    n_tasks: int
    n_runs: int
    displayable: bool


# --------------------------------------------------------------------------- #
# Ranking (framework §6)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class RankInput:
    """One agent's pass/total over the ranking scope."""

    agent: str
    c: int
    n: int


@dataclass(frozen=True)
class LeaderboardEntry:
    """One ranked agent.

    Agents are ordered by Wilson lower bound. Ties are expressed as rank ranges:
    agent a strictly out-ranks b iff LCB_a > p-hat_b (framework §6 v0.1 rule).
    Provisional agents (n < 5) are excluded from ranking; their rank_low /
    rank_high are None.
    """

    agent: str
    pass_rate: float
    wilson_low: float
    wilson_high: float
    n: int
    provisional: bool
    rank_low: int | None
    rank_high: int | None
