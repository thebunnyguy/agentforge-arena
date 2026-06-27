# audit/ — versioned external audit trail

External, evidence-backed audits of AgentForge Arena. One folder per audit run.

| Audit | Commit | Date | Score | Where |
|---|---|---|---:|---|
| **audit-1** | `036cde4` | 2026-06-20 | 53/100 | repo-root `AUDIT_REPORT.md` / `AUDIT_SCORECARD.md` / `AUDIT_FINDINGS.json` (later rewritten in place to a post-P0 re-audit at `f70eb6d`, 75/100). The original 53/100 inventory is preserved in `audit-2/` as the audit-1 baseline. |
| **audit-2** | `798a5b3` | 2026-06-20 | 75/100 | [`audit-2/`](audit-2/) |

Each `audit-N/` folder contains `AUDIT_REPORT.md`, `AUDIT_SCORECARD.md`,
`AUDIT_FINDINGS.json`, and `audit_summary.html`. Audits are read-only: no
production code is changed by the audit itself. Files here are untracked unless
explicitly committed.
