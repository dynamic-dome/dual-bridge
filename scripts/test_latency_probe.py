"""Smoke test: latency_probe writes into the endpoint's send lane.
    python test_latency_probe.py
"""
from __future__ import annotations
import importlib, os, sys, tempfile
from pathlib import Path


def _fresh(endpoint: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="probe-s2a-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_probe_writes_to_send_lane() -> None:
    _fresh("claude@laptop-a")  # sends on A-to-B
    import bridge_common as bc; importlib.reload(bc)
    import latency_probe as lp; importlib.reload(lp)
    bc.ensure_dirs()
    task_id, _start = lp._write_probe(1)
    tasks = list(bc.lane_outbox("A-to-B").glob("task-*.md"))
    assert len(tasks) == 1, f"probe not in A-to-B send lane: {tasks}"
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(tasks[0]))
    assert fm["adapter"] == "echo"
    assert fm["from"] == "claude@laptop-a" and fm["to"] == "codex@laptop-b"
    assert fm["task_id"] == task_id
    print("  probe OK — writes into send-lane with from/to/adapter")


def main() -> int:
    print("=== latency_probe Smoke ===")
    failed = 0
    for t in [test_probe_writes_to_send_lane]:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 40)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {1-failed}/1 ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
