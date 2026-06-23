import builtins
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import setup


def _write_cli(tmp_path, name):
    if os.name == "nt":
        path = tmp_path / f"{name}.cmd"
        path.write_text("@echo off\r\necho ok\r\n", encoding="utf-8")
    else:
        path = tmp_path / name
        path.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def test_setup_main_runs_full_pipeline_and_writes_valid_config(monkeypatch, tmp_path):
    claude = _write_cli(tmp_path, "claude")
    codex = _write_cli(tmp_path, "codex")
    template = tmp_path / "template-config.json"
    target = tmp_path / "config.json"
    template.write_text(
        json.dumps(
            {
                "round_timeout": 1500,
                "codex_timeout": 1500,
                "max_rounds": 4,
                "poll_interval": 5.0,
                "poller_interval": 15,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DUAL_BRIDGE_CONFIG", str(template))
    monkeypatch.setattr(
        setup.Scout,
        "detect",
        lambda self: {"claude": str(claude), "codex": str(codex)},
    )

    answers = iter(["0", "y"])
    monkeypatch.setattr(builtins, "input", lambda prompt="": next(answers))

    assert setup.main(config_path=target) == 0
    assert target.exists()

    config = json.loads(target.read_text(encoding="utf-8"))
    for key in (
        "round_timeout",
        "codex_timeout",
        "max_rounds",
        "poll_interval",
        "poller_interval",
        "nodes",
        "endpoints",
    ):
        assert key in config

    assert config["nodes"]["A"]["model"] == "claude"
    assert config["nodes"]["B"]["model"] == "codex"
    assert config["endpoints"]["A"]["command"] == str(claude)
    assert config["endpoints"]["B"]["command"] == str(codex)
