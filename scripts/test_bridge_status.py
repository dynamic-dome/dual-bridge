"""Tests for the read-only Bridge-Status-Dashboard (bridge_status.py).

Dual-runnable like the rest of the suite:
    python -m pytest scripts/test_bridge_status.py
    python scripts/test_bridge_status.py

Isolated via the autouse conftest fixture (DUAL_BRIDGE_ROOT -> tmp dir). Every
test builds a small lane/state tree by hand and asserts the scanners read it
correctly WITHOUT mutating anything (the dashboard is a pure read lens).
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path


def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-status-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    # State-Ordner (Loops/Eskalationen) hermetisch isolieren, sonst leaken
    # LOOP-*.jsonl/ESCALATION-*.md zwischen Tests in das reale scripts/state/.
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_status as bs
    importlib.reload(bs)
    return bc, bs


def _write_task(bc, lane: str, *, task_id: str, status: str = "open",
                kind: str = "implement", adapter: str = "codex",
                claimed: str | None = None, created: str | None = None,
                loop_id: str = "", round_no: str = "", with_task_id: bool = True,
                name_override: str | None = None) -> Path:
    """Write a task file into a lane outbox. claimed=<device> stamps a claim
    marker in the filename. with_task_id=False simulates a half-written file."""
    bc.ensure_dirs()
    fm = {
        "created": created or bc.now_iso(), "schema_version": "2",
        "agent": "codex@laptop-b", "from": "codex@laptop-b",
        "to": "claude@laptop-a", "purpose": "handoff",
        "status": status, "kind": kind, "adapter": adapter,
        "claimed_by": "", "claimed_at": "",
    }
    if with_task_id:
        fm["task_id"] = task_id
    if loop_id:
        fm["loop_id"] = loop_id
        fm["round"] = round_no
    body = "## Auftrag\nmach was\n\n## Ergebnis\n<offen>\n"
    if name_override is not None:
        name = name_override
    elif claimed:
        name = f"task-{task_id}.claimed-{claimed}-abcd1234.md"
    else:
        name = f"task-{task_id}.md"
    path = bc.lane_outbox(lane) / name
    bc.write_text_utf8(path, bc.build_document(fm, body))
    return path


def _write_result(bc, lane: str, *, task_id: str, status: str = "done",
                  verdict: str = "", name_override: str | None = None) -> Path:
    bc.ensure_dirs()
    fm = {"created": bc.now_iso(), "agent": "claude@laptop-a",
          "from": "claude@laptop-a", "to": "codex@laptop-b",
          "status": status, "task_id": task_id, "kind": "review"}
    if verdict:
        fm["verdict"] = verdict
    name = name_override or f"result-{task_id}.md"
    path = bc.lane_inbox(lane) / name
    bc.write_text_utf8(path, bc.build_document(fm, "## Antwort\nok\n"))
    return path


def _snapshot_tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- (a) lane bucket counts -------------------------------------------------
def test_scan_lane_counts_buckets() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    tid1 = "20260603-120000-000001-0-aaaa"
    tid2 = "20260603-120000-000002-0-bbbb"
    tid3 = "20260603-120000-000003-0-cccc"
    _write_task(bc, "A-to-B", task_id=tid1, status="open")
    _write_task(bc, "A-to-B", task_id=tid2, status="claimed", claimed="laptop-b")
    _write_result(bc, "A-to-B", task_id=tid3, status="done")
    # one processed + one error file
    bc.lane_processed("A-to-B").mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(bc.lane_processed("A-to-B") / f"task-{tid1}.md", "x")
    bc.lane_errors("A-to-B").mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(bc.lane_errors("A-to-B") / "task-bogus.md", "x")

    st = bs.scan_lane("A-to-B")
    assert len(st.open) == 1, st.open
    assert len(st.claimed) == 1, st.claimed
    assert len(st.results) == 1, st.results
    assert st.processed_count == 1
    assert st.errors_count == 1
    # claimed task surfaces the device from the filename
    assert st.claimed[0].claimed_device == "laptop-b", st.claimed[0]
    print("  status OK — scan_lane classifies open/claimed/results/processed/errors")


# --- (b) conflict copies are not counted as valid tasks ---------------------
def test_scan_lane_skips_conflict_copies() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    tid = "20260603-120000-000001-0-aaaa"
    _write_task(bc, "A-to-B", task_id=tid, status="open")
    _write_task(bc, "A-to-B", task_id=tid, status="open",
                name_override=f"task-{tid} (1).md")
    st = bs.scan_lane("A-to-B")
    assert len(st.open) == 1, "conflict copy must not be a second open task"
    assert st.conflicts_count == 1, st.conflicts_count
    print("  status OK — Drive conflict copies counted separately, not as tasks")


# --- (c) half-written task (no task_id) -> incomplete bucket, no crash ------
def test_scan_lane_half_written_task_is_incomplete() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    _write_task(bc, "A-to-B", task_id="ignored", status="open",
                with_task_id=False, name_override="task-half.md")
    st = bs.scan_lane("A-to-B")
    assert len(st.open) == 0, "a task without task_id is not a valid open task"
    assert st.incomplete_count == 1, st.incomplete_count
    print("  status OK — half-written task (no task_id) -> incomplete, never valid")


# --- (d) errors quarantine surfaced ----------------------------------------
def test_scan_lane_errors_surfaced() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bc.ensure_dirs()
    bc.lane_errors("B-to-A").mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(bc.lane_errors("B-to-A") / "task-evil.md", "x")
    bc.write_text_utf8(bc.lane_errors("B-to-A") / "task-evil2.md", "x")
    st = bs.scan_lane("B-to-A")
    assert st.errors_count == 2, st.errors_count
    print("  status OK — _errors/ quarantine counted prominently")


# --- (e) loop history reconstruction + bad line tolerated -------------------
def test_scan_loops_reads_last_round_and_tolerates_bad_line() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    loop_id = "loop-20260603-120000-000001-0-aaaa"
    path = bs.STATE_DIR / f"LOOP-{loop_id}.jsonl"
    lines = [
        json.dumps({"round": 0, "side": "goal-loop", "verdict": "rejected",
                    "commit": "aaa111", "status": "done", "ts": "t0"}),
        "THIS IS NOT JSON",  # must be tolerated, not crash
        json.dumps({"round": 1, "side": "goal-loop", "verdict": "accepted",
                    "commit": "bbb222", "status": "done", "ts": "t1"}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    loops = bs.scan_loops(bs.STATE_DIR)
    assert len(loops) == 1, loops
    lp = loops[0]
    assert lp.loop_id == loop_id
    assert lp.last_round == 1, lp.last_round
    assert lp.last_verdict == "accepted", lp.last_verdict
    assert lp.last_commit == "bbb222"
    assert lp.state == "accepted", lp.state
    print("  status OK — scan_loops reconstructs last round, survives a bad line")


# --- (f) loop with escalation file -> escalated ------------------------------
def test_scan_loops_marks_escalated_when_escalation_file_present() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    loop_id = "loop-20260603-120000-000002-0-bbbb"
    (bs.STATE_DIR / f"LOOP-{loop_id}.jsonl").write_text(
        json.dumps({"round": 2, "side": "goal-loop", "verdict": "rejected",
                    "commit": "ccc333", "status": "done", "ts": "t"}) + "\n",
        encoding="utf-8")
    esc_fm = {"loop_id": loop_id, "trigger": "reviewer_requested", "round": "2",
              "branch": f"bridge/{loop_id}", "commit": "ccc333",
              "exit_reason": "escalation", "created": bc.now_iso()}
    bc.write_text_utf8(bs.STATE_DIR / f"ESCALATION-{loop_id}.md",
                       bc.build_document(esc_fm, "## Ziel\nx\n"))
    loops = bs.scan_loops(bs.STATE_DIR)
    assert loops[0].state == "escalated", loops[0].state
    assert loops[0].escalation_trigger == "reviewer_requested"
    print("  status OK — loop with ESCALATION file -> state escalated + trigger")


# --- (g) escalations scan ignores _processed/ -------------------------------
def test_scan_escalations_ignores_processed() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    live_id = "loop-20260603-120000-000003-0-cccc"
    done_id = "loop-20260603-120000-000004-0-dddd"
    fm_live = {"loop_id": live_id, "trigger": "stagnation", "round": "1",
               "branch": f"bridge/{live_id}", "commit": "d1",
               "exit_reason": "escalation", "created": bc.now_iso()}
    bc.write_text_utf8(bs.STATE_DIR / f"ESCALATION-{live_id}.md",
                       bc.build_document(fm_live, "## Ziel\nx\n"))
    proc = bs.STATE_DIR / "_processed"
    proc.mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(proc / f"ESCALATION-{done_id}.md",
                       bc.build_document(dict(fm_live, loop_id=done_id), "## Ziel\nx\n"))
    escs = bs.scan_escalations(bs.STATE_DIR)
    ids = {e.loop_id for e in escs}
    assert live_id in ids and done_id not in ids, ids
    print("  status OK — scan_escalations lists open only, ignores _processed/")


# --- (h) liveness via lock + pid -------------------------------------------
def test_scan_liveness_live_and_dead(monkeypatch=None) -> None:
    _fresh_bridge()
    bc, bs = _reload()
    lock = bs.STATE_DIR / "fake-poller.lock"
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock.write_text("4242\n2026-06-03T12:00:00\n", encoding="utf-8")

    # live pid
    orig = bc._pid_alive
    bc._pid_alive = lambda pid, must_match=None: pid == 4242
    try:
        live = bs.scan_lock(lock, label="poller")
        assert live.running is True and live.pid == 4242, live
        # dead pid
        bc._pid_alive = lambda pid, must_match=None: False
        dead = bs.scan_lock(lock, label="poller")
        assert dead.running is False, dead
    finally:
        bc._pid_alive = orig
    print("  status OK — scan_lock reports running for live pid, not for dead pid")


# --- (i) json format -------------------------------------------------------
def test_render_json_has_top_level_keys() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    _write_task(bc, "A-to-B", task_id="20260603-120000-000001-0-aaaa")
    report = bs.build_report()
    text = bs.render_json(report)
    obj = json.loads(text)  # must be valid JSON
    for key in ("escalations", "errors", "loops", "lanes", "liveness", "summary"):
        assert key in obj, f"missing top-level key {key!r} in {list(obj)}"
    print("  status OK — render_json emits valid JSON with all top-level keys")


# --- (j) text render puts urgent items first --------------------------------
def test_render_text_urgent_first() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bs.STATE_DIR.mkdir(parents=True, exist_ok=True)
    # one escalation + one error file + one normal open task
    loop_id = "loop-20260603-120000-000009-0-9999"
    fm = {"loop_id": loop_id, "trigger": "max_rounds", "round": "3",
          "branch": f"bridge/{loop_id}", "commit": "z9",
          "exit_reason": "escalation", "created": bc.now_iso()}
    bc.write_text_utf8(bs.STATE_DIR / f"ESCALATION-{loop_id}.md",
                       bc.build_document(fm, "## Ziel\nx\n"))
    bc.lane_errors("A-to-B").mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(bc.lane_errors("A-to-B") / "task-bad.md", "x")
    _write_task(bc, "A-to-B", task_id="20260603-120000-000010-0-1010")

    report = bs.build_report()
    text = bs.render_text(report)
    i_esc = text.upper().find("ESKALATION")
    i_err = text.find("_errors")
    i_lane = text.find("lane-A-to-B")
    assert i_esc != -1 and i_err != -1 and i_lane != -1, text
    assert i_esc < i_lane, "escalations must render before lane tables"
    assert i_err < i_lane, "_errors must render before lane tables"
    print("  status OK — render_text shows escalations + _errors before lane tables")


# --- (k) empty tree -> calm output, no crash --------------------------------
def test_build_report_empty_tree() -> None:
    _fresh_bridge()
    bc, bs = _reload()
    bc.ensure_dirs()
    report = bs.build_report()
    text = bs.render_text(report)
    assert isinstance(text, str) and text.strip(), "empty tree must still render"
    assert report.summary["open"] == 0
    print("  status OK — empty bridge tree renders a calm all-quiet report")


# --- read-only invariant: scanning never mutates the tree -------------------
def test_dashboard_is_read_only() -> None:
    root = _fresh_bridge()
    bc, bs = _reload()
    tid = "20260603-120000-000001-0-aaaa"
    _write_task(bc, "A-to-B", task_id=tid, status="open")
    _write_task(bc, "A-to-B", task_id="20260603-120000-000002-0-bbbb",
                status="claimed", claimed="laptop-b")
    _write_result(bc, "B-to-A", task_id="20260603-120000-000003-0-cccc")
    before = _snapshot_tree(root)
    bs.build_report()           # full scan
    bs.render_text(bs.build_report())
    bs.render_json(bs.build_report())
    after = _snapshot_tree(root)
    assert before == after, f"dashboard mutated the tree!\nbefore={before}\nafter={after}"
    print("  status OK — build_report + render do NOT mutate the lane tree (read-only)")


def main() -> int:
    print("=== Bridge-Status-Dashboard-Tests ===")
    tests = [
        test_scan_lane_counts_buckets,
        test_scan_lane_skips_conflict_copies,
        test_scan_lane_half_written_task_is_incomplete,
        test_scan_lane_errors_surfaced,
        test_scan_loops_reads_last_round_and_tolerates_bad_line,
        test_scan_loops_marks_escalated_when_escalation_file_present,
        test_scan_escalations_ignores_processed,
        test_scan_liveness_live_and_dead,
        test_render_json_has_top_level_keys,
        test_render_text_urgent_first,
        test_build_report_empty_tree,
        test_dashboard_is_read_only,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
