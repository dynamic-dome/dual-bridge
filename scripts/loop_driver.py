"""Stage-1 self-driving A<->B ping-pong loop driver (runs on Laptop A).

A is the conductor: it does its own work step inline (local runner), writes a
task into the A->B lane, waits for B's result (with a per-round timeout), then
takes B's payload into the next round. B stays the unchanged handoff_poll worker.

Loop state/history lives A-side in scripts/state/LOOP-<loop_id>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bridge_common as bc
import runners  # noqa: F401 -- registers echo + increment
import codex_adapter  # noqa: F401
import claude_adapter  # noqa: F401

STATE_DIR = Path(__file__).resolve().parent / "state"


def write_round_task(loop_id: str, round_no: int, payload: str,
                     adapter: str) -> str:
    """Write an open loop task into THIS endpoint's send lane. Returns task_id."""
    bc.ensure_dirs()
    me = bc.this_endpoint()
    lane = bc.send_lane()
    to = next((ep for ep, cfg in bc.ENDPOINTS.items()
               if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": me, "from": me, "to": to, "purpose": "handoff",
        "status": "open", "task_id": task_id, "kind": "echo",
        "adapter": adapter,
        "loop_id": loop_id, "round": str(round_no), "payload": payload,
        "claimed_by": "", "claimed_at": "",
    }
    body = (f"## Auftrag\n{payload}\n\n"
            "## Akzeptanzkriterien\n- [ ] Result im inbox/ mit demselben task_id\n\n"
            "## Ergebnis\n<wird vom Empfaenger gefuellt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def _is_conflict_copy(name: str) -> bool:
    return "(" in name and ")" in name


def wait_for_result(task_id: str, timeout: int, interval: int = 5):
    """Poll THIS endpoint's receive-lane inbox for result-<task_id>.md until it
    appears or `timeout` seconds elapse. Returns the result frontmatter dict, or
    None on timeout. Drive conflict copies ('(1)') are ignored. Archives the
    consumed result into _processed/ so it is not re-read next round."""
    lane = bc.receive_lanes()[0]
    target_name = f"result-{task_id}.md"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = bc.lane_inbox(lane) / target_name
        if path.exists() and not _is_conflict_copy(path.name):
            fm, _ = bc.parse_frontmatter(bc.read_text_utf8(path))
            try:
                (bc.lane_processed(lane) / target_name).unlink(missing_ok=True)
                path.replace(bc.lane_processed(lane) / target_name)
            except OSError:
                pass  # best-effort archive; we already have the fm
            return fm
        time.sleep(interval)
    return None
