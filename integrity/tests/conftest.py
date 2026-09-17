from pathlib import Path

import pytest

# integrity/fixtures/, a SIBLING of integrity/tests/, not a subdirectory of it:
# each fixture's grading/test_hidden.py etc. is task CONTENT the engine grades
# in its own subprocess, not a pytest test of this test suite. root
# pyproject.toml's testpaths includes "integrity/tests" — if fixtures lived
# under it, pytest's own collection would walk into every fixture's
# grading/test_hidden.py and snapshot/tests_visible/test_visible.py and try to
# import their (colliding, per-fixture) `pkg` packages directly, which is
# exactly the failure mode the real tasks/ directory avoids by not being
# listed in testpaths at all.
FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES_ROOT
