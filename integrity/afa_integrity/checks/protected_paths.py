"""Protected-path / grader-tampering probes (mission §14).

Constructs REAL adversarial diffs (via the same public capture_diff every real
run goes through — never the private glob-matching helpers directly) that try
to touch: every configured protected glob, every always-protected auto-
executed basename, and a path outside the editable_paths allow-list when one
is configured. Each must come back touched_protected=True, i.e. any diff that
does this would fail the scope gate (G=0) before ever reaching the grader.

This also runs the one probe that surfaces the always-protected-basename gap
this engine's own runner touch didn't (and can't, by design) fully close: a
package directory literally named `_pytest/` shadowing the real `_pytest`
package. That gap is reported as a finding + limitation, not a failing status
for this check — it is a known, documented boundary of the current
`LocalSandbox` threat model (mission §14/§25), not a defect this check exists
to fail tasks over.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from afa_runner.diffing import capture_diff
from afa_runner.task import Task

from ..model import CheckStatus, Finding, IntegrityCheckResult, Severity

PROBE_CONTENT = "# afa_integrity protected-path probe\n"


def _diff_for_injected_files(task: Task, files: dict[str, str]):
    tmp_root = Path(tempfile.mkdtemp(prefix="afa_integrity_probe_"))
    workspace = tmp_root / "workspace"
    try:
        shutil.copytree(task.snapshot_dir, workspace)
        for rel, content in files.items():
            dest = workspace / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        return capture_diff(
            task.snapshot_dir,
            workspace,
            protected_globs=task.protected_paths,
            editable_globs=task.editable_paths,
        )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _concretize_glob(pattern: str) -> str | None:
    """Best-effort concrete example path that should match `pattern`. Returns
    None (skip, don't guess) for a pattern shape not confidently handled."""
    if pattern == "**":
        return "__afa_probe__.py"
    if pattern.endswith("/**"):
        return pattern[: -len("/**")] + "/__afa_probe__.py"
    if pattern.startswith("**/"):
        rest = pattern[len("**/") :]
        return rest.replace("*", "afa_probe") if "*" in rest else rest
    if "*" in pattern:
        return pattern.replace("*", "afa_probe")
    return pattern


_ALWAYS_PROTECTED_PROBES = (
    "conftest.py",
    "sitecustomize.py",
    "usercustomize.py",
    "pytest.ini",
    "tox.ini",
    "setup.cfg",
    "pyproject.toml",
    "pytest.py",
)


def run_protected_paths_check(task: Task) -> tuple[IntegrityCheckResult, list[Finding]]:
    start = time.monotonic()
    findings: list[Finding] = []
    failures: list[str] = []
    skipped: list[str] = []
    checked: list[str] = []

    # 1. Every configured protected glob.
    for pattern in task.protected_paths:
        concrete = _concretize_glob(pattern)
        if concrete is None:
            skipped.append(pattern)
            continue
        diff = _diff_for_injected_files(task, {concrete: PROBE_CONTENT})
        checked.append(f"glob:{pattern}->{concrete}")
        if not diff.touched_protected:
            failures.append(
                f"protected glob {pattern!r} did not flag injected file "
                f"{concrete!r} as a scope violation"
            )

    # 2. Always-protected auto-executed basenames, injected inside the
    #    editable package (the realistic attack surface) when we can identify
    #    one, else at snapshot root.
    editable_prefix = ""
    if task.editable_paths:
        first = task.editable_paths[0]
        editable_prefix = first[: -len("/**")] + "/" if first.endswith("/**") else ""
    for basename in _ALWAYS_PROTECTED_PROBES:
        rel = editable_prefix + basename
        diff = _diff_for_injected_files(task, {rel: PROBE_CONTENT})
        checked.append(f"always_protected:{rel}")
        if not diff.touched_protected:
            failures.append(
                f"always-protected basename {basename!r} did not flag "
                f"{rel!r} as a scope violation"
            )

    # 2b. Always-protected auto-executed SUFFIX (*.pth — a site-loaded import
    #     hook that executes code at interpreter startup). Distinct from the
    #     basename list above: afa_runner.diffing.ALWAYS_PROTECTED_SUFFIXES
    #     is matched by suffix, not exact basename, so it needs its own probe.
    pth_rel = editable_prefix + "afa_probe.pth"
    pth_diff = _diff_for_injected_files(task, {pth_rel: PROBE_CONTENT})
    checked.append(f"always_protected_suffix:{pth_rel}")
    if not pth_diff.touched_protected:
        failures.append(
            f"always-protected suffix '.pth' did not flag {pth_rel!r} as a "
            "scope violation"
        )

    # 3. Allow-list enforcement: a path outside editable_paths, not matching
    #    any protected glob either, must still be a scope violation when an
    #    allow-list is configured.
    if task.editable_paths:
        rel = "__afa_probe_outside_allowlist__.py"
        diff = _diff_for_injected_files(task, {rel: PROBE_CONTENT})
        checked.append(f"allowlist_outside:{rel}")
        if not diff.touched_protected:
            failures.append(
                f"path {rel!r} outside every editable_paths glob was NOT "
                "flagged as a scope violation — the allow-list is not being "
                "enforced as a deny-by-default gate"
            )

    # 4. Known, documented gap: a directory literally named `_pytest/`
    #    shadowing the real _pytest package. Not fixable by basename matching
    #    (it's a directory-name shadow, not an auto-executed config file) and
    #    fixing it generally edges into the sandboxing redesign this mission
    #    explicitly excludes (§14/§25) — report as a finding + limitation,
    #    not a check failure.
    #
    #    IMPORTANT (corrected after empirical testing — see docs/agents/
    #    ORACLE.md "Corrected: the _pytest shadow-package finding was
    #    overstated"): a `_pytest/` package NESTED inside an editable_paths
    #    subtree (e.g. "searchkit/_pytest/__init__.py") is empirically
    #    HARMLESS. `python -m pytest` never adds the editable package
    #    directory itself to sys.path — only the cleanroom ROOT is on
    #    sys.path[0] — so a nested `_pytest/` is only ever importable as
    #    "searchkit._pytest", never as the bare top-level "_pytest" the real
    #    pytest package needs; a controlled test confirms `import _pytest`
    #    from inside the editable package still resolves to the real
    #    site-packages one. Only a `_pytest/` placed at the CLEANROOM ROOT
    #    itself (confirmed separately, by controlled test, to crash pytest's
    #    own bootstrap via ImportError) would be dangerous — and every task's
    #    editable_paths allow-list already rejects ANY root-level write
    #    (probe 3 above), independent of this basename/suffix mechanism. This
    #    probe is therefore only meaningfully testing a hypothetical FUTURE
    #    deny-list-only task (editable_prefix empty), where nothing else
    #    would stop a root-level `_pytest/` — not a live gap in any task in
    #    the current pack.
    is_root_level_probe = not editable_prefix
    shadow_rel = f"{editable_prefix}_pytest/__init__.py" if editable_prefix else "_pytest/__init__.py"
    shadow_diff = _diff_for_injected_files(task, {shadow_rel: PROBE_CONTENT})
    checked.append(f"pytest_shadow_dir:{shadow_rel}")
    shadow_gap_confirmed = not shadow_diff.touched_protected
    if shadow_gap_confirmed and is_root_level_probe:
        findings.append(
            Finding(
                finding_id="protected_paths.pytest_shadow_package",
                category="isolation",
                severity=Severity.HIGH,
                summary=(
                    "This deny-list-only task has no editable_paths allow-list, "
                    "and a root-level `_pytest/` package directory is not "
                    "flagged as a protected-path violation — empirically "
                    "confirmed to crash pytest's own bootstrap if planted "
                    "there during grading."
                ),
                detail=(
                    f"Injecting {shadow_rel!r} at the snapshot ROOT was NOT "
                    "flagged as touching a protected path. "
                    "ALWAYS_PROTECTED_BASENAMES matches basenames, not "
                    "directory names, and this task has no editable_paths "
                    "allow-list to reject an out-of-scope root write either — "
                    "so nothing currently stops a root-level `_pytest/` "
                    "package from shadowing the real one for the grading "
                    "pytest invocation. See docs/agents/ORACLE.md for the "
                    "empirical confirmation and why this is reported rather "
                    "than silently fixed here."
                ),
                evidence={"probe_path": shadow_rel, "touched_protected": False},
            )
        )
    elif shadow_gap_confirmed:
        findings.append(
            Finding(
                finding_id="protected_paths.pytest_shadow_package_nested",
                category="isolation",
                severity=Severity.INFO,
                summary=(
                    "A `_pytest/` package nested inside this task's editable "
                    "subtree is not flagged as a protected-path violation, "
                    "but empirical testing confirms this is NOT currently "
                    "exploitable."
                ),
                detail=(
                    f"Injecting {shadow_rel!r} (nested inside the editable "
                    "package, not at the snapshot root) was NOT flagged as "
                    "touching a protected path — but `python -m pytest` never "
                    "adds the editable package directory itself to sys.path, "
                    "so this nested `_pytest/` is only importable as "
                    "`<package>._pytest`, never as the bare top-level "
                    "`_pytest` the real pytest package needs; a controlled "
                    "test confirms `import _pytest` still resolves to the "
                    "real site-packages module. Recorded as a structural gap "
                    "(no basename/suffix rule catches a directory named "
                    "`_pytest`) that would only matter if this task ever lost "
                    "its editable_paths allow-list, not as a live weakness "
                    "today. See docs/agents/ORACLE.md."
                ),
                evidence={"probe_path": shadow_rel, "touched_protected": False, "exploitable_today": False},
            )
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    evidence = {
        "checked": checked,
        "skipped_globs": skipped,
        "failures": failures,
        "pytest_shadow_package_gap_confirmed": shadow_gap_confirmed,
        "pytest_shadow_package_exploitable_today": shadow_gap_confirmed and is_root_level_probe,
    }

    if failures:
        return (
            IntegrityCheckResult(
                check_id="protected_paths.tampering_probes",
                category="isolation",
                status=CheckStatus.FAIL,
                severity=Severity.CRITICAL,
                description=(
                    f"{len(failures)} protected-path probe(s) failed: an "
                    "injected file that should have been a scope violation "
                    "was not flagged. Details in evidence.failures."
                ),
                evidence=evidence,
                duration_ms=duration_ms,
            ),
            findings,
        )

    return (
        IntegrityCheckResult(
            check_id="protected_paths.tampering_probes",
            category="isolation",
            status=CheckStatus.PASS,
            severity=Severity.INFO,
            description=(
                f"All {len(checked) - (1 if shadow_gap_confirmed else 0)} "
                "protected-path/allow-list probes correctly flagged a scope "
                "violation."
                + (
                    " One exploitable gap (a ROOT-level `_pytest/` shadow "
                    "package, confirmed by controlled test to crash pytest's "
                    "own bootstrap) was also probed and confirmed on this "
                    "deny-list-only task — see findings."
                    if (shadow_gap_confirmed and is_root_level_probe)
                    else (
                        " A `_pytest/` package nested inside the editable "
                        "subtree is also not flagged, but empirical testing "
                        "confirms it is NOT exploitable under this task's "
                        "current editable_paths allow-list — see findings."
                        if shadow_gap_confirmed
                        else ""
                    )
                )
            ),
            evidence=evidence,
            duration_ms=duration_ms,
        ),
        findings,
    )
