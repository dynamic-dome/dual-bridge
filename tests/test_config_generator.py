import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.config_generator import generate_config


def _template(monkeypatch, tmp_path, data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("DUAL_BRIDGE_CONFIG", str(path))
    return path


@pytest.fixture
def scout_result():
    return {
        "claude": r"C:\Tools\claude.cmd",
        "codex": r"C:\Tools\codex.exe",
    }


def test_generate_config_fills_required_model_and_command_fields(monkeypatch, tmp_path, scout_result):
    _template(monkeypatch, tmp_path, {"round_timeout": 1500, "poll_interval": 5.0})

    config = generate_config(
        scout_result,
        {"node_a": "claude", "node_b": "codex"},
    )

    assert config["round_timeout"] == 1500
    assert config["poll_interval"] == 5.0
    assert config["nodes"]["A"]["model"] == "claude"
    assert config["nodes"]["B"]["model"] == "codex"
    assert config["endpoints"]["A"]["command"] == r"C:\Tools\claude.cmd"
    assert config["endpoints"]["B"]["command"] == r"C:\Tools\codex.exe"


def test_generate_config_result_is_json_serializable(monkeypatch, tmp_path, scout_result):
    _template(monkeypatch, tmp_path, {"max_rounds": 4})

    config = generate_config(
        scout_result,
        {"node_a": "codex", "node_b": "claude"},
    )

    encoded = json.dumps(config)
    assert json.loads(encoded)["nodes"]["A"]["model"] == "codex"


def test_generate_config_supports_nested_wizard_result(monkeypatch, tmp_path, scout_result):
    _template(monkeypatch, tmp_path, {"nodes": {"A": {"label": "Laptop A"}}})

    config = generate_config(
        scout_result,
        {"nodes": {"A": {"model": "codex"}, "B": {"model": "claude"}}},
    )

    assert config["nodes"]["A"] == {"label": "Laptop A", "model": "codex"}
    assert config["nodes"]["B"]["model"] == "claude"
    assert config["endpoints"]["A"]["command"] == r"C:\Tools\codex.exe"
    assert config["endpoints"]["B"]["command"] == r"C:\Tools\claude.cmd"


def test_generate_config_uses_executable_name_when_scout_has_no_path(monkeypatch, tmp_path):
    _template(monkeypatch, tmp_path, {"codex_timeout": 900})

    config = generate_config(
        {"claude": r"C:\Tools\claude.cmd", "codex": None},
        {"node_a": "claude", "node_b": "codex"},
    )

    assert config["endpoints"]["A"]["command"] == r"C:\Tools\claude.cmd"
    assert config["endpoints"]["B"]["command"] == "codex"


def test_generate_config_rejects_missing_required_wizard_fields(monkeypatch, tmp_path, scout_result):
    _template(monkeypatch, tmp_path, {})

    with pytest.raises(ValueError, match="node B model"):
        generate_config(scout_result, {"node_a": "claude"})
