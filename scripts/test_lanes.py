"""Stage 2a lane + routing tests. Pure stdlib + assert:
    python test_lanes.py
Isolated via DUAL_BRIDGE_ROOT -> tmp dir; DUAL_BRIDGE_ENDPOINT sets identity.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-s2a-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_lane_dirs_resolve_under_lane() -> None:
    _fresh_bridge()
    import bridge_common as bc
    importlib.reload(bc)
    ob = bc.lane_outbox("A-to-B")
    ib = bc.lane_inbox("A-to-B")
    assert ob.name == "outbox" and ob.parent.name == "lane-A-to-B", ob
    assert ib.name == "inbox" and ib.parent.name == "lane-A-to-B", ib
    assert bc.lane_outbox("B-to-A").parent.name == "lane-B-to-A"
    print("  lane OK — lane_outbox/lane_inbox resolve under lane-<dir>/")


def test_default_lane_backcompat() -> None:
    _fresh_bridge()
    import bridge_common as bc
    importlib.reload(bc)
    assert bc.outbox_dir().parent.name.startswith("lane-"), bc.outbox_dir()
    assert bc.outbox_dir().name == "outbox"
    assert bc.inbox_dir().name == "inbox"
    print("  lane OK — legacy outbox_dir/inbox_dir map to the default lane")


def test_runner_result_to_markdown() -> None:
    import runners
    importlib.reload(runners)
    r = runners.RunnerResult(status="done", antwort="hallo welt")
    md = r.to_markdown(task_id="T1", claimed_by="x", claimed_at="now")
    assert "## Quelle" in md and "hallo welt" in md
    err = runners.RunnerResult(status="error", error_text="kaputt")
    assert "## FEHLER" in err.to_markdown(task_id="T2", claimed_by="x", claimed_at="now")
    print("  runner OK — RunnerResult.to_markdown renders done + error")


def test_run_echo() -> None:
    import runners
    importlib.reload(runners)
    r = runners.run_echo(auftrag="spiegel mich", fm={"task_id": "T1"}, workroot=None)
    assert r.status == "done" and "spiegel mich" in r.antwort
    print("  runner OK — run_echo returns done with the auftrag echoed")


def test_registry_has_echo() -> None:
    import runners
    importlib.reload(runners)
    assert "echo" in runners.RUNNERS and callable(runners.RUNNERS["echo"])
    print("  runner OK — RUNNERS registry contains echo")


def test_codex_registered_and_allowlist() -> None:
    import runners, codex_adapter
    importlib.reload(runners); importlib.reload(codex_adapter)
    assert "codex" in runners.RUNNERS, "codex runner not registered"
    # Allowlist: a repo not on a non-empty allowlist -> error before any clone.
    os.environ["DUAL_BRIDGE_REPO_ALLOWLIST"] = "github.com/dynamic-dome/*"
    try:
        r = runners.RUNNERS["codex"](
            auftrag="x",
            fm={"task_id": "20260531-000000-000000-0-aaaa",
                "repo": "https://evil.example/malware.git", "base_branch": "main"},
            workroot=Path(tempfile.mkdtemp(prefix="cdx-al-")),
        )
    finally:
        del os.environ["DUAL_BRIDGE_REPO_ALLOWLIST"]
    assert r.status == "error" and "allowlist" in (r.error_text or "").lower(), \
        f"expected allowlist rejection, got {r.status}/{r.error_text}"
    print("  codex OK — registered + repo-allowlist rejects non-listed repo before clone")


def test_poll_dispatches_on_adapter_echo() -> None:
    _fresh_bridge("claude@laptop-a")  # A receives on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nspiegel\n"))
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert rfm["status"] == "done" and "spiegel" in rbody
    print("  poll OK — adapter:echo dispatched via registry, result in B-to-A inbox")


def test_poll_to_filter_skips_foreign() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "x@y", "to": "codex@laptop-b",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))
    assert hp.process_one(task, lane="B-to-A") is False, "fremder to muss übersprungen werden"
    print("  poll OK — to-filter skips task addressed to another endpoint")


def test_poll_unknown_adapter_errors() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "bogus",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))
    hp.process_one(task, lane="B-to-A")
    rfm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert rfm["status"] == "error", "unbekannter adapter muss status:error liefern"
    print("  poll OK — unknown adapter -> status:error, no crash")


def test_poll_watch_wait_uses_event_without_sleep() -> None:
    import handoff_poll as hp

    slept = []

    def fake_sleep(_interval):
        slept.append(_interval)

    class FakeEvent:
        def __init__(self):
            self.waited = None
            self.cleared = False

        def wait(self, interval):
            self.waited = interval
            return True

        def clear(self):
            self.cleared = True

    event = FakeEvent()
    original_sleep = hp.time.sleep
    hp.time.sleep = fake_sleep
    try:
        hp._wait_for_next_poll(99, event)
    finally:
        hp.time.sleep = original_sleep
    assert event.waited == 99
    assert event.cleared is True
    assert slept == [], "watchdog wake path must not call time.sleep directly"
    print("  watch OK — event wait wakes poller without direct sleep")


def test_poll_watch_wait_falls_back_to_sleep() -> None:
    import handoff_poll as hp

    slept = []
    original_sleep = hp.time.sleep
    hp.time.sleep = lambda interval: slept.append(interval)
    try:
        hp._wait_for_next_poll(7, None)
    finally:
        hp.time.sleep = original_sleep
    assert slept == [7]
    print("  watch OK — missing watchdog falls back to interval sleep")


def test_start_outbox_watch_schedules_receive_lanes_and_wakes() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_poll as hp; importlib.reload(hp)

    class FakeEvent:
        def __init__(self):
            self.set_count = 0

        def set(self):
            self.set_count += 1

    class FakeObserver:
        def __init__(self):
            self.scheduled = []
            self.started = False

        def schedule(self, handler, path, recursive=False):
            self.scheduled.append((handler, Path(path), recursive))

        def start(self):
            self.started = True

    class EventObject:
        is_directory = False

        def __init__(self, src_path=None, dest_path=None):
            self.src_path = src_path
            self.dest_path = dest_path

    observer, event = hp._start_outbox_watch(
        observer_factory=FakeObserver,
        event_factory=FakeEvent,
        handler_base=object,
    )
    assert observer.started is True
    assert len(observer.scheduled) == len(bc.receive_lanes())
    handler, path, recursive = observer.scheduled[0]
    assert path == bc.lane_outbox("B-to-A")
    assert recursive is False
    handler.on_created(EventObject(src_path=str(path / "task-20260603-000000-000000-0-abcd.md")))
    handler.on_created(EventObject(src_path=str(path / "task-20260603-000000-000000-0-abcd (1).md")))
    handler.on_moved(EventObject(dest_path=str(path / "task-20260603-000000-000000-0-abce.md")))
    assert event.set_count == 2, "fresh task create/move should wake; conflict copy should not"
    print("  watch OK — receive-lane outbox watcher schedules and wakes on task events")


def test_writer_uses_send_lane_and_adapter() -> None:
    _fresh_bridge("codex@laptop-b")  # B sends on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    # codex is build-level — matches implement (was: claude=read, mismatch, now blocked by risk-policy)
    rc = hw.main(["bau das feature", "--kind", "implement", "--adapter", "codex"])
    assert rc == 0
    tasks = list(bc.lane_outbox("B-to-A").glob("task-*.md"))
    assert len(tasks) == 1, f"task not in B-to-A send lane: {tasks}"
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(tasks[0]))
    assert fm["adapter"] == "codex"
    assert fm["from"] == "codex@laptop-b" and fm["to"] == "claude@laptop-a"
    print("  write OK — task in send-lane outbox with adapter + from/to set")


def test_b_to_a_roundtrip_echo() -> None:
    """B writes (codex@laptop-b sends on B-to-A), A polls (claude@laptop-a
    receives on B-to-A) and echoes, B collects. Direction reversed by config."""
    root = _fresh_bridge("codex@laptop-b")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    # B writes the task.
    assert hw.main(["spiegel mich bitte", "--adapter", "echo"]) == 0

    # Switch identity to A and poll.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
    import handoff_poll as hp; importlib.reload(hp)
    import runners; importlib.reload(runners)
    n = hp.poll_once()
    assert n == 1, f"A sollte genau 1 Task in B-to-A verarbeiten, war {n}"

    # Switch back to B and collect.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "codex@laptop-b"
    importlib.reload(bc)
    import handoff_collect as hc; importlib.reload(hc)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = hc.collect_once(peek=True)
    assert got == 1, "B sollte genau 1 Result einsammeln"
    assert "spiegel mich bitte" in buf.getvalue()
    print("  roundtrip OK — B→A echo end-to-end, reversed by configuration only")


def main() -> int:
    print("=== Stage-2a Lane-Tests ===")
    tests = [test_lane_dirs_resolve_under_lane, test_default_lane_backcompat,
             test_runner_result_to_markdown, test_run_echo, test_registry_has_echo,
             test_codex_registered_and_allowlist,
             test_poll_dispatches_on_adapter_echo, test_poll_to_filter_skips_foreign,
             test_poll_unknown_adapter_errors,
             test_poll_watch_wait_uses_event_without_sleep,
             test_poll_watch_wait_falls_back_to_sleep,
             test_start_outbox_watch_schedules_receive_lanes_and_wakes,
             test_writer_uses_send_lane_and_adapter,
             test_b_to_a_roundtrip_echo]
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
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
