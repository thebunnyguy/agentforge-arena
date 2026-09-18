# Benchmark Integrity Engine — audit evidence storage policy

The first ORACLE pass committed the full per-task JSON+Markdown evidence for
all 24 tasks in both QUICK and FULL mode (`integrity/pack-audit/{quick,full}
-tasks/*`) — every routine, unremarkable task included. That does not scale:
every future audit run would add another 48+ files, most of them identical
in substance to the previous run for tasks nothing happened to.

## What gets committed permanently

- **Pack-level summaries**, JSON + Markdown, for the mode(s) actually run
  (`integrity/pack-audit/{quick,full}-summary.{json,md}`). These alone are
  enough to see the whole pack's status distribution and every task's
  one-line reason at a glance, and they're small regardless of pack size.
- **Per-task detailed evidence** (`integrity/pack-audit/full-tasks/<id>.{json,md}`)
  **only** for tasks that are:
  - `INVALID` or `NEEDS_REVIEW` after the run (the whole reason detailed
    evidence exists is to let a human dig into *why*), or
  - the subject of a version-impact/remediation-manifest entry for this run
    (so the manifest's claims are checkable against the actual evidence that
    produced them), or
  - otherwise flagged as worth a permanent record in the accompanying
    commit message (e.g. a HEALTHY task whose evidence is cited as a
    worked example).
- **Version-impact / remediation manifests**
  (`integrity/pack-audit/remediation-manifest-<date-or-commit>.{json,md}`),
  always, for any run that follows a remediation pass.

## What is generated but NOT normally committed

- Per-task JSON+MD for tasks that are `HEALTHY` or `PROVISIONAL` with
  nothing new to report — the pack summary's one line already says
  everything a reader needs, and the full evidence is trivially
  reproducible on demand (`python -m afa_integrity audit <id> --full`).
- QUICK-mode per-task evidence whenever a FULL-mode run for the same
  commit exists — FULL is a superset; keeping both is pure duplication.
- Any intermediate/transient output (a single ad-hoc verification run, a
  scratch re-audit while debugging a fix) — these belong in the ORACLE
  journal as evidence *quoted inline*, not as a committed artifact.

## Rationale

A pack audit's value to a future reader is almost entirely in (a) the
one-line-per-task summary table and (b) the small number of tasks that
actually need a human's attention. Committing the other ~20 tasks' full
JSON dumps every run adds repo weight with no corresponding increase in
what anyone can actually learn from git history — the summary already
told them "HEALTHY, nothing to see here," and if they want to check that
claim, re-running the (deterministic, reproducible) engine is one command.

## Applying this policy to prior commits

The original 24-task x 2-mode evidence set (`c48e1ef`) is superseded
history and left as-is (rewriting it would rewrite published commits this
branch has already pushed). Going forward, each new pack-audit commit
follows the rule above: summaries always, per-task detail only where it
earns its place.
