import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cli_scout import Scout


def test_detect_returns_paths_for_both_clis(monkeypatch):
    paths = {
        "claude": r"C:\Tools\claude.cmd",
        "codex": r"C:\Tools\codex.exe",
    }

    monkeypatch.setattr("shutil.which", lambda name: paths.get(name))

    assert Scout().detect() == paths


def test_detect_returns_none_for_missing_cli(monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda name: r"C:\Tools\claude.cmd" if name == "claude" else None,
    )

    assert Scout().detect() == {
        "claude": r"C:\Tools\claude.cmd",
        "codex": None,
    }


def test_detect_returns_none_when_no_clis_exist(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert Scout().detect() == {
        "claude": None,
        "codex": None,
    }
