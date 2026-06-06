"""Tests for _pid_alive() identity-aware liveness (anti PID-recycling, L11)."""
from __future__ import annotations

import os
import bridge_common as bc


def test_no_match_arg_keeps_existence_only_behavior(monkeypatch):
    # Without must_match, an existing pid is alive regardless of cmdline.
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "anything")
    assert bc._pid_alive(os.getpid()) is True


def test_dead_pid_is_not_alive():
    assert bc._pid_alive(-1) is False
    assert bc._pid_alive(0) is False


def test_recycled_pid_without_marker_is_stale(monkeypatch):
    # PID exists but its cmdline is a recycled svchost -> not OUR poller.
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: r"C:\Windows\system32\svchost.exe -k netsvcs")
    assert bc._pid_alive(1234, must_match="handoff_poll") is False


def test_matching_marker_is_alive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(
        bc, "_pid_cmdline",
        lambda pid: r"python -X utf8 C:\...\scripts\handoff_poll.py --watch")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_marker_match_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: r"python HANDOFF_POLL.PY --watch")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_failed_cmdline_query_is_conservatively_alive(monkeypatch):
    # Query failed (empty) but the pid exists -> assume alive, never false-negative
    # a real running poller into a double-claim.
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_marker_required_but_pid_dead_is_not_alive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: False)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "handoff_poll")
    assert bc._pid_alive(1234, must_match="handoff_poll") is False
