import subprocess
import sys
import time

import pytest

import subprocess_util as su


def test_runs_and_captures_stdout(tmp_path):
    cmd = [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"]
    cp = su.run_with_tree_kill(cmd, tmp_path, "hallo", timeout=30)
    assert cp.returncode == 0
    assert cp.stdout.strip() == "hallo"


def test_timeout_raises_and_kills(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    t0 = time.time()
    with pytest.raises(subprocess.TimeoutExpired):
        su.run_with_tree_kill(cmd, tmp_path, "", timeout=1)
    assert time.time() - t0 < 15


def test_kill_process_tree_never_raises_on_dead_pid():
    su._kill_process_tree(2_147_483_000)
