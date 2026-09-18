"""Benchmark Integrity Engine CLI launcher (house sys.path-injection style —
see docs/BENCHMARK_INTEGRITY.md and integrity/afa_integrity/cli.py for the
actual argument parsing).

Usage:
    python examples/benchmark_audit.py audit fix-binary-search --full
    python examples/benchmark_audit.py audit --all --quick --json-dir reports/integrity
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(_ROOT / "kernel"), str(_ROOT / "runner"), str(_ROOT / "integrity")]

from afa_integrity.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
