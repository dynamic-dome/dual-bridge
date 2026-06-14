"""Relay-loop tests. Isoliert via conftest (tmp ROOT/STATE/LOCK, Endpoint A,
Runner re-registriert). Builder werden injiziert (build_runner_for) + b_tick-Hook,
kein echtes codex/claude."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import bridge_common as bc
import pytest


def test_parse_relay_seed_ziel_and_leitplanken():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed(
        "## Ziel\nEine CLI-Toolsammlung.\n\n## Leitplanken\n- nur stdlib\n- [ ] mit Test\n")
    assert ziel == "Eine CLI-Toolsammlung."
    assert lp == ["nur stdlib", "mit Test"]


def test_parse_relay_seed_ziel_only():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed("## Ziel\nFreie Richtung.\n")
    assert ziel == "Freie Richtung." and lp == []


def test_parse_relay_seed_missing_ziel_raises():
    import loop_driver
    with pytest.raises(ValueError):
        loop_driver.parse_relay_seed("## Leitplanken\n- x\n")


def test_other_builder_rotates_codex_and_claude():
    import loop_driver
    assert loop_driver._other_builder("codex") == "claude-build"
    assert loop_driver._other_builder("claude-build") == "codex"
