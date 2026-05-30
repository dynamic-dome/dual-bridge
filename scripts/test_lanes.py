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


def main() -> int:
    print("=== Stage-2a Lane-Tests ===")
    tests = [test_lane_dirs_resolve_under_lane, test_default_lane_backcompat,
             test_runner_result_to_markdown, test_run_echo, test_registry_has_echo]
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
