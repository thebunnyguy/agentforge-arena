"""AgentForge Arena — local app backend (Phases 1-2).

A single local FastAPI app that PROJECTS the frozen kernel/runner aggregates and
the raw SQLite layer into JSON for the SPA. It adds NO new scoring or statistics:
all numbers come from afa_runner.report (leaderboard, domain_profile,
task_aggregate) and from direct read-only SQL against reports/runs.sqlite.

Trusted local single-user tool. No untrusted-agent / sandbox-isolation claims.
"""

from __future__ import annotations

__version__ = "0.1.0"
