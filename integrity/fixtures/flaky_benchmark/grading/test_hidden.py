"""Hidden test: also reads an env var a test-only Sandbox wrapper toggles per
grade call (see integrity/tests/test_audit_fixtures.py's FlipSandbox), so the
SAME correct artifact (the reference solution) deterministically alternates
between passing and failing across repeated grades — a controlled stand-in
for real grader nondeterminism, without relying on real randomness."""

import os

from pkg import add_one


def test_add_one_and_flaky_toggle():
    assert add_one(1) == 2
    assert os.environ.get("AFA_TEST_FLAKY_TOGGLE") == "0"
