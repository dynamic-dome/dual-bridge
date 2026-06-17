"""Tests for the read-only Codex rollout watchdog.

The detector scans tmp session trees only. It must not touch real Codex
sessions, bridge state, processes, or databases during the default dry run.
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path


def _reload():
    import rollout_watchdog as rw

    importlib.reload(rw)
    return rw


def _write_jsonl(path: Path, records: list[dict] | list[str], *, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for record in records:
        if isinstance(record, str):
            lines.append(record)
        else:
            lines.append(json.dumps(record, sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def _call(call_id: str, timestamp: str, name: str = "shell_command") -> dict:
    return {
        "type": "item.completed",
        "timestamp": timestamp,
        "item": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
        },
    }


def _output(call_id: str, timestamp: str) -> dict:
    return {
        "type": "item.completed",
        "timestamp": timestamp,
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": "ok",
        },
    }


def test_stale_last_function_call_without_output_is_hanging(tmp_path: Path) -> None:
    rw = _reload()
    sessions = tmp_path / "sessions"
    _write_jsonl(
        sessions / "2026-06-16" / "rollout-old.jsonl",
        [_call("old", "2026-06-17T08:00:00Z"), _output("old", "2026-06-17T08:00:01Z")],
        mtime_ns=100,
    )
    newest = sessions / "2026-06-17" / "rollout-new.jsonl"
    _write_jsonl(
        newest,
        [_call("call_1", "2026-06-17T09:00:00Z", "apply_patch")],
        mtime_ns=200,
    )

    result = rw.detect_hanging_builder(
        sessions_root=sessions,
        stale_seconds=300,
        now="2026-06-17T09:10:00Z",
    )

    assert result["status"] == "hanging"
    assert result["hanging"] is True
    assert result["idle_seconds"] == 600
    assert result["latest_log"] == str(newest)
    assert result["last_call"]["call_id"] == "call_1"
    assert result["last_call"]["name"] == "apply_patch"
    assert result["last_call"]["line"] == 1


def test_complete_function_calls_are_not_hanging(tmp_path: Path) -> None:
    rw = _reload()
    sessions = tmp_path / "sessions"
    _write_jsonl(
        sessions / "2026-06-17" / "rollout-complete.jsonl",
        [
            _call("call_1", "2026-06-17T09:00:00Z"),
            _output("call_1", "2026-06-17T09:00:03Z"),
            _call("call_2", "2026-06-17T09:00:04Z"),
            _output("call_2", "2026-06-17T09:00:05Z"),
        ],
        mtime_ns=300,
    )

    result = rw.detect_hanging_builder(
        sessions_root=sessions,
        stale_seconds=300,
        now="2026-06-17T09:10:00Z",
    )

    assert result["status"] == "ok"
    assert result["hanging"] is False
    assert result["last_call"] is None
    assert result["idle_seconds"] is None


def test_empty_or_broken_jsonl_is_graceful_unknown_without_crash(tmp_path: Path) -> None:
    rw = _reload()
    sessions = tmp_path / "sessions"
    _write_jsonl(
        sessions / "2026-06-17" / "rollout-broken.jsonl",
        ["", "{not-json", json.dumps({"type": "turn.started"})],
        mtime_ns=400,
    )

    result = rw.detect_hanging_builder(
        sessions_root=sessions,
        stale_seconds=300,
        now="2026-06-17T09:10:00Z",
    )

    assert result["hanging"] is False
    assert result["status"] == "unknown"
    assert result["reason"] == "no_function_calls"
    assert result["parse_errors"] == 1


def test_scan_is_deterministic_over_sorted_scandir_walk(tmp_path: Path) -> None:
    rw = _reload()
    sessions = tmp_path / "sessions"
    _write_jsonl(
        sessions / "z-date" / "rollout-b.jsonl",
        [_call("later", "2026-06-17T09:00:00Z")],
        mtime_ns=500,
    )
    _write_jsonl(
        sessions / "a-date" / "rollout-a.jsonl",
        [_call("earlier", "2026-06-17T08:00:00Z")],
        mtime_ns=100,
    )

    first = rw.detect_hanging_builder(
        sessions_root=sessions,
        stale_seconds=300,
        now="2026-06-17T09:10:00Z",
    )
    second = rw.detect_hanging_builder(
        sessions_root=sessions,
        stale_seconds=300,
        now="2026-06-17T09:10:00Z",
    )

    assert first == second
    assert first["last_call"]["call_id"] == "later"


def test_default_dry_run_does_not_kill_release_or_requeue(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    rw = _reload()
    sessions = tmp_path / "sessions"
    lease_file = tmp_path / "lease.lock"
    requeue_log = tmp_path / "requeue.jsonl"
    kill_marker = tmp_path / "kill-called"
    lease_file.write_text("held\n", encoding="utf-8")
    _write_jsonl(
        sessions / "2026-06-17" / "rollout-stale.jsonl",
        [_call("call_1", "2026-06-17T09:00:00Z")],
        mtime_ns=600,
    )

    def fake_kill(_pid: int) -> None:
        kill_marker.write_text("bad\n", encoding="utf-8")

    monkeypatch.setattr(rw, "_kill_process_tree", fake_kill)

    rc = rw.main(
        [
            "--sessions-root",
            str(sessions),
            "--stale-seconds",
            "300",
            "--now",
            "2026-06-17T09:10:00Z",
            "--pid",
            "999999",
            "--lease-file",
            str(lease_file),
            "--requeue-log",
            str(requeue_log),
            "--format",
            "json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["result"]["hanging"] is True
    assert payload["action"]["execute"] is False
    assert lease_file.exists()
    assert not requeue_log.exists()
    assert not kill_marker.exists()


def test_action_plan_escalates_after_three_requeues(tmp_path: Path) -> None:
    rw = _reload()
    result = {
        "hanging": True,
        "last_call": {"call_id": "call_1"},
    }

    action = rw.plan_actions(
        result,
        pid=None,
        lease_file=None,
        requeue_log=tmp_path / "requeue.jsonl",
        requeue_count=3,
        max_requeues=3,
    )

    kinds = [item["kind"] for item in action["planned"]]
    assert "escalate_owner" in kinds
    assert "requeue" not in kinds
