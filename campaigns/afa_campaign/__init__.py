"""Campaign tooling for fresh, real-backend AgentForge benchmark campaigns.

A campaign is a frozen plan (``manifest.json``: models x tasks x repetitions at
pinned task versions/digests and generation settings) executed ONLY through the
ATLAS evaluation lifecycle (Jobs API -> evaluation snapshot -> trials -> worker
-> raw runs), one evaluation per (model, task) cell. A campaign-owned ledger
records which evaluation IDs belong to the campaign, so completeness, analysis and
the official leaderboard are computed from campaign-owned evidence only - never
from "whatever real rows happen to be in the database".
"""

__all__ = ["paths"]
