import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wizard import InteractiveWizard


def _mock_input(monkeypatch, answers):
    pending = iter(answers)
    prompts = []

    def fake_input(prompt=""):
        prompts.append(prompt)
        return next(pending)

    monkeypatch.setattr(builtins, "input", fake_input)
    return prompts


def test_ask_accepts_valid_lane_selection(monkeypatch):
    prompts = _mock_input(monkeypatch, ["1", "y"])

    result = InteractiveWizard().ask({
        "claude": r"C:\Tools\claude.cmd",
        "codex": r"C:\Tools\codex.exe",
    })

    assert result == {"node_a": "codex", "node_b": "claude"}
    assert len(prompts) == 2


def test_ask_retries_until_lane_selection_is_valid(monkeypatch):
    prompts = _mock_input(monkeypatch, ["x", "2", "0", "yes"])

    result = InteractiveWizard().ask({
        "claude": r"C:\Tools\claude.cmd",
        "codex": r"C:\Tools\codex.exe",
    })

    assert result == {"node_a": "claude", "node_b": "codex"}
    assert len(prompts) == 4


def test_ask_confirms_auto_suggestion_when_only_one_cli_exists(monkeypatch):
    prompts = _mock_input(monkeypatch, ["y"])

    result = InteractiveWizard().ask({
        "claude": r"C:\Tools\claude.cmd",
        "codex": None,
    })

    assert result == {"node_a": "claude", "node_b": "codex"}
    assert len(prompts) == 1
