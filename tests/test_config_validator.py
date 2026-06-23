import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.config_validator import validate_config


def _write_cli(tmp_path, name, exit_code=0):
    if os.name == "nt":
        path = tmp_path / f"{name}.cmd"
        path.write_text(f"@echo off\r\nexit /b {exit_code}\r\n", encoding="utf-8")
    else:
        path = tmp_path / name
        path.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def _valid_config(claude_cmd, codex_cmd, **extra):
    config = {
        "round_timeout": 1500,
        "codex_timeout": 1500,
        "max_rounds": 4,
        "poll_interval": 5.0,
        "poller_interval": 15,
        "nodes": {
            "A": {"model": "claude"},
            "B": {"model": "codex"},
        },
        "endpoints": {
            "A": {"command": str(claude_cmd)},
            "B": {"command": str(codex_cmd)},
        },
    }
    config.update(extra)
    return config


def test_valid_config_passes_and_returns_true(monkeypatch, tmp_path):
    claude = _write_cli(tmp_path, "claude")
    codex = _write_cli(tmp_path, "codex")
    monkeypatch.setattr("shutil.which", lambda name: None)

    assert validate_config(_valid_config(claude, codex)) is True


def test_missing_required_keys_raise_value_error(tmp_path):
    config = _valid_config(_write_cli(tmp_path, "claude"), _write_cli(tmp_path, "codex"))
    del config["nodes"]["B"]["model"]

    with pytest.raises(ValueError, match="nodes.B.model"):
        validate_config(config)


def test_cli_existence_check_accepts_shutil_which(monkeypatch, tmp_path):
    claude = _write_cli(tmp_path, "claude")
    codex = _write_cli(tmp_path, "codex")

    def fake_which(name):
        return str(claude) if name == "claude" else str(codex) if name == "codex" else None

    monkeypatch.setattr("shutil.which", fake_which)

    assert validate_config(_valid_config("claude", "codex")) is True


def test_cli_existence_check_rejects_missing_command(monkeypatch, tmp_path):
    claude = _write_cli(tmp_path, "claude")
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ValueError, match="endpoints.B.command"):
        validate_config(_valid_config(claude, tmp_path / "missing-codex"))


def test_dry_run_errors_are_detected(monkeypatch, tmp_path):
    claude = _write_cli(tmp_path, "claude", exit_code=0)
    codex = _write_cli(tmp_path, "codex", exit_code=3)
    monkeypatch.setattr("shutil.which", lambda name: None)

    with pytest.raises(ValueError, match="dry-run failed.*endpoints.B.command"):
        validate_config(_valid_config(claude, codex, dry_run=True))
