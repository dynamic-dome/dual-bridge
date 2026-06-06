"""Tests for the central config.json layer (bridge_common.bridge_config /
config_value).

The bridge's tunable knobs (timeouts, intervals, max-rounds, schedule defaults)
used to live as scattered hardcoded `default=...` values and ad-hoc env-var
reads. This layer makes config.json the single editable source of truth, with a
strict precedence chain:

    explicit CLI arg  >  env var  >  config.json  >  hardcoded fallback

CLI args are not tested here (they bypass config_value entirely by passing the
value straight into the function parameter). This file pins the lower three
rungs and the fail-soft behaviour (missing / malformed file must never crash).
"""
from __future__ import annotations

import importlib
import json

import pytest


def _fresh(monkeypatch, *, config_path=None):
    """Reload bridge_common with a controlled DUAL_BRIDGE_CONFIG override."""
    import bridge_common as bc
    if config_path is None:
        monkeypatch.delenv("DUAL_BRIDGE_CONFIG", raising=False)
    else:
        monkeypatch.setenv("DUAL_BRIDGE_CONFIG", str(config_path))
    importlib.reload(bc)
    return bc


def _write_config(path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# --- bridge_config() loading ------------------------------------------------

def test_missing_config_returns_empty_dict(monkeypatch, tmp_path):
    bc = _fresh(monkeypatch, config_path=tmp_path / "does-not-exist.json")
    assert bc.bridge_config() == {}


def test_malformed_config_returns_empty_dict_without_raising(monkeypatch, tmp_path):
    bad = tmp_path / "config.json"
    bad.write_text("{ this is not json ", encoding="utf-8")
    bc = _fresh(monkeypatch, config_path=bad)
    # Fail-soft: a broken file must not crash the bridge — fall back to {}.
    assert bc.bridge_config() == {}


def test_valid_config_is_loaded(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"round_timeout": 900, "max_rounds": 6})
    bc = _fresh(monkeypatch, config_path=cfg)
    assert bc.bridge_config()["round_timeout"] == 900
    assert bc.bridge_config()["max_rounds"] == 6


def test_config_is_cached_per_path(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"round_timeout": 900})
    bc = _fresh(monkeypatch, config_path=cfg)
    first = bc.bridge_config()
    # Mutate the file on disk; cached load must return the original value.
    _write_config(cfg, {"round_timeout": 111})
    assert bc.bridge_config()["round_timeout"] == 900
    # use_cache=False forces a re-read (the manual-edit-and-reload path).
    assert bc.bridge_config(use_cache=False)["round_timeout"] == 111


# --- config_value() precedence ----------------------------------------------

def test_fallback_used_when_nothing_set(monkeypatch, tmp_path):
    bc = _fresh(monkeypatch, config_path=tmp_path / "none.json")
    monkeypatch.delenv("DUAL_BRIDGE_ROUND_TIMEOUT", raising=False)
    assert bc.config_value("round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int) == 300


def test_config_beats_fallback(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"round_timeout": 900})
    bc = _fresh(monkeypatch, config_path=cfg)
    monkeypatch.delenv("DUAL_BRIDGE_ROUND_TIMEOUT", raising=False)
    assert bc.config_value("round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int) == 900


def test_env_beats_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"round_timeout": 900})
    bc = _fresh(monkeypatch, config_path=cfg)
    monkeypatch.setenv("DUAL_BRIDGE_ROUND_TIMEOUT", "1800")
    assert bc.config_value("round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int) == 1800


def test_cast_is_applied(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    # JSON value stored as a string; cast=int must coerce it.
    _write_config(cfg, {"round_timeout": "900"})
    bc = _fresh(monkeypatch, config_path=cfg)
    monkeypatch.delenv("DUAL_BRIDGE_ROUND_TIMEOUT", raising=False)
    val = bc.config_value("round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int)
    assert val == 900 and isinstance(val, int)


def test_uncastable_value_falls_through_to_fallback(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"round_timeout": "not-a-number"})
    bc = _fresh(monkeypatch, config_path=cfg)
    monkeypatch.delenv("DUAL_BRIDGE_ROUND_TIMEOUT", raising=False)
    # A garbage config value must not crash; degrade to the hardcoded fallback.
    assert bc.config_value("round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int) == 300


def test_env_var_none_skips_env_lookup(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    _write_config(cfg, {"some_key": 42})
    bc = _fresh(monkeypatch, config_path=cfg)
    # env_var=None means "this knob has no env override" — config still wins.
    assert bc.config_value("some_key", None, 7, cast=int) == 42


def test_default_config_path_is_repo_root(monkeypatch, tmp_path):
    # Without an override the path is <repo-root>/config.json, i.e. the parent of
    # scripts/. We don't assert it exists, only that the resolver points there.
    bc = _fresh(monkeypatch, config_path=None)
    expected = (bc.Path(bc.__file__).resolve().parent.parent / "config.json")
    assert bc.default_config_path() == expected
