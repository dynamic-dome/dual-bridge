"""Tests for hostname-based endpoint resolution (override -> hostname -> error)."""
from __future__ import annotations

import importlib
import pytest


def _fresh(monkeypatch, *, endpoint=None, hostname=None):
    """Reload bridge_common with a controlled env + hostname, return the module."""
    import bridge_common as bc
    if endpoint is None:
        monkeypatch.delenv("DUAL_BRIDGE_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", endpoint)
    importlib.reload(bc)
    if hostname is not None:
        monkeypatch.setattr(bc.socket, "gethostname", lambda: hostname)
    return bc


def test_override_wins_over_hostname(monkeypatch):
    bc = _fresh(monkeypatch, endpoint="codex@laptop-b", hostname="K472HEXXZACKBUU")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_dome_dynamics_maps_to_laptop_b(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="DOME-DYNAMICS")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_is_case_insensitive(monkeypatch):
    # gethostname() really returns "DoMe-Dynamics" (mixed case) on this machine.
    bc = _fresh(monkeypatch, endpoint=None, hostname="DoMe-Dynamics")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_k472_maps_to_laptop_a(monkeypatch):
    # Real laptop-a hostname is "K472HEXXZackBUUM" (mixed case, trailing M) --
    # gethostname() returns it as-is; the table key is uppercase + host.upper().
    bc = _fresh(monkeypatch, endpoint=None, hostname="K472HEXXZackBUUM")
    assert bc.this_endpoint() == "claude@laptop-a"


def test_hostname_k472_uppercase_also_maps(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="K472HEXXZACKBUUM")
    assert bc.this_endpoint() == "claude@laptop-a"


def test_unknown_host_without_override_raises(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="SOME-RANDOM-PC")
    with pytest.raises(ValueError) as exc:
        bc.this_endpoint()
    msg = str(exc.value)
    assert "SOME-RANDOM-PC" in msg          # names the detected host
    assert "DUAL_BRIDGE_ENDPOINT" in msg    # tells the user how to fix it
