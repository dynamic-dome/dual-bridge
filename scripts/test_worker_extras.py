"""Tests fuer die zwei v1-Worker-Extras der Ops-Konsole:

1. Verbunden-Cross-Link: loop_driver druckt einen stabilen `loop_id=`-Marker,
   job_poll._parse_loop_id liest ihn aus dem (vollen) stdout, process_item reicht
   ihn in den result_payload -> DCO kann Job<->Loop verknuepfen.
2. Worker-Heartbeat: job_poll.write_heartbeat schreibt ein echtes Drive-Artefakt
   (lane-B-to-A/_worker-heartbeat.json), run_watch ruft es je Poll-Iteration.

Isolation: die dual-bridge conftest lenkt DUAL_BRIDGE_ROOT/STATE auf tmp.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import bridge_common as bc
import job_poll
import loop_driver


# --- Cross-Link --------------------------------------------------------------
def test_loop_id_marker_printed(capsys):
    lid = loop_driver._next_loop_id()
    out = capsys.readouterr().out
    assert lid.startswith("loop-")
    assert f"loop_id={lid}" in out


def test_parse_loop_id_extracts_marker():
    text = "blabla\n[A] loop_id=loop-20260616-120000-abcdef\nweiter"
    assert job_poll._parse_loop_id(text) == "loop-20260616-120000-abcdef"


def test_parse_loop_id_none_when_absent():
    assert job_poll._parse_loop_id("kein marker hier") is None


def test_process_item_passes_loop_id_through():
    item = SimpleNamespace(input_text="repo=https://x/y\nbaue", job_id="j1")
    payload: dict = {}

    def fake_run(**kw):
        return {"exit": 0, "loop_id": "loop-xyz", "stdout": "s"}

    rc = job_poll.process_item(item, run_fn=fake_run, out_payload=payload)
    assert rc == 0
    assert payload["loop_id"] == "loop-xyz"


# --- Worker-Heartbeat --------------------------------------------------------
def test_write_heartbeat_creates_artifact():
    path = job_poll.write_heartbeat()
    assert path is not None and path.is_file()
    assert path.name == "_worker-heartbeat.json"
    assert path.parent.name == "lane-B-to-A"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "ts" in data and "host" in data


def test_run_watch_writes_heartbeat_each_iteration():
    def fake_tick(source, **kw):
        return 0

    def fake_sleep(_s):
        raise KeyboardInterrupt  # nach der ersten Iteration abbrechen

    rc = job_poll.run_watch(object(), interval=1, max_rounds=1, round_timeout=1,
                            tick_fn=fake_tick, sleep_fn=fake_sleep)
    assert rc == 0
    hb = bc.lane_root("B-to-A") / "_worker-heartbeat.json"
    assert hb.is_file()
