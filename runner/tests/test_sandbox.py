"""Tests for afa_runner.sandbox.LocalSandbox (framework §9).

These exercise the observable contract of LocalSandbox.run independently of its
implementation: exit-code propagation, stdout/stderr capture, the deterministic
env overlay, caller-env override, PATH inheritance, cwd, string-vs-list cmd
dispatch, and the timeout path (SIGKILL of the process group, timed_out=True,
exit_code=-1, partial output preserved, and the wall clock not exceeding the
budget by much).

Run from the project root:  python -m pytest runner/tests/test_sandbox.py -q
The pytest pythonpath (pyproject.toml) puts `runner/` on sys.path, so this
imports the sandbox submodule directly without pulling in sibling stubs.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from afa_runner.sandbox import CommandResult, LocalSandbox, Sandbox


PY = sys.executable  # the interpreter running the tests; guaranteed present


def test_local_sandbox_satisfies_protocol():
    # The runtime_checkable Protocol should accept a LocalSandbox instance.
    assert isinstance(LocalSandbox(), Sandbox)


def test_string_cmd_runs_through_shell(tmp_path: Path):
    # Shell features (variable expansion / pipes) only work when shell=True,
    # which a *string* cmd must trigger.
    sb = LocalSandbox()
    res = sb.run("echo hello | tr a-z A-Z", cwd=tmp_path, timeout_s=10)
    assert isinstance(res, CommandResult)
    assert res.exit_code == 0
    assert res.timed_out is False
    assert res.stdout.strip() == "HELLO"
    assert res.stderr == ""


def test_list_cmd_runs_directly_without_shell(tmp_path: Path):
    # A list cmd is argv-direct: shell metacharacters must be passed verbatim as
    # arguments, not interpreted. We echo a literal pipe via python to prove no
    # shell touched it.
    sb = LocalSandbox()
    res = sb.run(
        [PY, "-c", "import sys; print(sys.argv[1])", "a|b>c"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.exit_code == 0
    assert res.stdout.strip() == "a|b>c"


def test_exit_code_propagation_nonzero(tmp_path: Path):
    sb = LocalSandbox()
    res = sb.run([PY, "-c", "import sys; sys.exit(7)"], cwd=tmp_path, timeout_s=10)
    assert res.exit_code == 7
    assert res.timed_out is False


def test_exit_code_propagation_zero(tmp_path: Path):
    sb = LocalSandbox()
    res = sb.run([PY, "-c", "pass"], cwd=tmp_path, timeout_s=10)
    assert res.exit_code == 0


def test_stdout_and_stderr_captured_separately(tmp_path: Path):
    sb = LocalSandbox()
    res = sb.run(
        [PY, "-c", "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR')"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.stdout == "OUT"
    assert res.stderr == "ERR"


def test_non_utf8_bytes_do_not_crash_capture(tmp_path: Path):
    # utf-8 decode with errors="replace": invalid bytes become U+FFFD, never raise.
    sb = LocalSandbox()
    res = sb.run(
        [PY, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.exit_code == 0
    assert "�" in res.stdout  # replacement char present, no exception thrown


def test_base_env_overlay_applied(tmp_path: Path):
    # The deterministic overlay must reach the child regardless of caller env.
    sb = LocalSandbox()
    res = sb.run(
        [PY, "-c",
         "import os; print(os.environ.get('PYTHONHASHSEED'), os.environ.get('TZ'))"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.stdout.strip() == "0 UTC"


def test_caller_env_overrides_base_env_and_adds_keys(tmp_path: Path):
    # Caller env wins over BASE_ENV for shared keys and contributes new ones.
    sb = LocalSandbox()
    res = sb.run(
        [PY, "-c",
         "import os; print(os.environ.get('TZ'), os.environ.get('AFA_CUSTOM'))"],
        cwd=tmp_path,
        timeout_s=10,
        env={"TZ": "America/New_York", "AFA_CUSTOM": "xyz"},
    )
    assert res.stdout.strip() == "America/New_York xyz"


def test_host_env_not_leaked_by_default(tmp_path: Path):
    # A variable set only in the host process must NOT appear in the child unless
    # the caller passes it explicitly. This is the isolation guarantee in §9.
    marker = "AFA_HOST_ONLY_MARKER"
    os.environ[marker] = "leaked"
    try:
        sb = LocalSandbox()
        res = sb.run(
            [PY, "-c", f"import os; print(repr(os.environ.get('{marker}')))"],
            cwd=tmp_path,
            timeout_s=10,
        )
        assert res.stdout.strip() == "None"
    finally:
        del os.environ[marker]


def test_inherit_path_true_passes_host_path(tmp_path: Path):
    sb = LocalSandbox(inherit_path=True)
    res = sb.run(
        [PY, "-c", "import os; print(os.environ.get('PATH', ''))"],
        cwd=tmp_path,
        timeout_s=10,
    )
    # The host PATH should be present (it is what lets python/pytest resolve).
    assert res.stdout.strip() == os.environ.get("PATH", "")
    assert res.stdout.strip() != ""


def test_inherit_path_false_omits_host_path(tmp_path: Path):
    # With inherit_path=False and no caller PATH, the child env carries no PATH
    # from the host. We ask python (invoked by absolute path) to report it.
    sb = LocalSandbox(inherit_path=False)
    res = sb.run(
        [PY, "-c", "import os; print(repr(os.environ.get('PATH')))"],
        cwd=tmp_path,
        timeout_s=10,
    )
    assert res.stdout.strip() == "None"


def test_cwd_is_respected(tmp_path: Path):
    sub = tmp_path / "workspace"
    sub.mkdir()
    sb = LocalSandbox()
    res = sb.run([PY, "-c", "import os; print(os.getcwd())"], cwd=sub, timeout_s=10)
    # Resolve both sides: macOS /tmp may be a symlink to /private/tmp.
    assert Path(res.stdout.strip()).resolve() == sub.resolve()


def test_timeout_kills_and_reports(tmp_path: Path):
    # A command that sleeps far longer than the budget must be killed and flagged.
    sb = LocalSandbox()
    start = time.monotonic()
    res = sb.run([PY, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout_s=1)
    elapsed = time.monotonic() - start

    assert res.timed_out is True
    assert res.exit_code == -1
    # We returned shortly after the 1s budget, nowhere near the 30s sleep.
    assert elapsed < 15
    assert res.duration_ms >= 0


def test_timeout_preserves_partial_output(tmp_path: Path):
    # Output produced before the timeout must survive in the result. The child
    # prints a marker (flushed) and then sleeps past the budget.
    sb = LocalSandbox()
    code = "import time, sys; sys.stdout.write('PARTIAL'); sys.stdout.flush(); time.sleep(30)"
    res = sb.run([PY, "-c", code], cwd=tmp_path, timeout_s=1)
    assert res.timed_out is True
    assert "PARTIAL" in res.stdout


def test_timeout_kills_whole_process_group(tmp_path: Path):
    # A child that spawns a long-lived grandchild: on timeout the grandchild must
    # also die (process-group SIGKILL), proven by it not finishing its write to a
    # sentinel file after the parent is killed.
    sentinel = tmp_path / "grandchild_done.txt"
    # Parent spawns a detached grandchild that sleeps then writes the sentinel,
    # then the parent itself blocks past the budget.
    grandchild_code = (
        "import time;"
        f"time.sleep(8);"
        f"open({str(sentinel)!r}, 'w').write('alive')"
    )
    parent_code = (
        "import subprocess, sys, time;"
        f"subprocess.Popen([sys.executable, '-c', {grandchild_code!r}]);"
        "time.sleep(30)"
    )
    sb = LocalSandbox()
    res = sb.run([PY, "-c", parent_code], cwd=tmp_path, timeout_s=1)
    assert res.timed_out is True

    # Wait past the grandchild's 8s sleep. If the group kill worked, the
    # grandchild was killed before it could create the sentinel.
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if sentinel.exists():
            break
        time.sleep(0.2)
    assert not sentinel.exists(), "grandchild survived the process-group kill"


def test_duration_ms_reflects_wall_clock(tmp_path: Path):
    # A ~0.4s sleep should report a duration in a sane band around it.
    sb = LocalSandbox()
    res = sb.run([PY, "-c", "import time; time.sleep(0.4)"], cwd=tmp_path, timeout_s=10)
    assert res.exit_code == 0
    assert res.timed_out is False
    assert res.duration_ms >= 350  # at least roughly the sleep
    assert res.duration_ms < 10000  # and clearly under the timeout budget


def test_cmd_label_records_invocation(tmp_path: Path):
    sb = LocalSandbox()
    s = sb.run("true", cwd=tmp_path, timeout_s=10)
    assert s.cmd == "true"
    lst = sb.run([PY, "-c", "pass"], cwd=tmp_path, timeout_s=10)
    # List commands are recorded as a readable joined string.
    assert PY in lst.cmd and "-c" in lst.cmd
