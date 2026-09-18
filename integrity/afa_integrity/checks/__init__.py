"""Individual integrity checks. Each module exposes a run_<name>(...) function
returning an IntegrityCheckResult (never raises for an expected-shape failure —
that IS the result). afa_integrity.audit composes these into a full report.
"""
