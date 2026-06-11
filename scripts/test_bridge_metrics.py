"""Tests for read-only metrics over lane _processed/ archives."""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path


def _fresh_bridge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-metrics-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_metrics as bm
    importlib.reload(bm)
    return bc, bm


def _write_doc(bc, path: Path, fm: dict, body: str = "body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(path, bc.build_document(fm, body))


def _write_pair(
    bc,
    lane: str,
    *,
    task_id: str,
    task_created: str,
    result_created: str | None,
    result_claimed_at: str | None = None,
    verdict: str,
) -> None:
    processed = bc.lane_processed(lane)
    task_fm = {
        "created": task_created,
        "task_id": task_id,
        "status": "done",
        "kind": "review",
    }
    result_fm = {
        "task_id": task_id,
        "status": "done",
        "kind": "review",
        "verdict": verdict,
    }
    if result_created is not None:
        result_fm["created"] = result_created
    if result_claimed_at is not None:
        result_fm["claimed_at"] = result_claimed_at
    _write_doc(bc, processed / f"task-{task_id}.md", task_fm)
    _write_doc(bc, processed / f"result-{task_id}.md", result_fm)


def _snapshot_files(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_compute_metrics_counts_verdicts_and_durations_read_only() -> None:
    root = _fresh_bridge()
    bc, bm = _reload()
    _write_pair(
        bc,
        "A-to-B",
        task_id="20260611-100000-000001-0-aaaa",
        task_created="2026-06-11T10:00:00",
        result_created="2026-06-11T10:05:00",
        verdict="accepted",
    )
    _write_pair(
        bc,
        "A-to-B",
        task_id="20260611-101000-000002-0-bbbb",
        task_created="2026-06-11T10:10:00",
        result_created="2026-06-11T10:30:00",
        verdict="rejected",
    )
    _write_pair(
        bc,
        "B-to-A",
        task_id="20260611-102000-000003-0-cccc",
        task_created="2026-06-11T10:20:00",
        result_created=None,
        result_claimed_at="2026-06-11T10:35:00",
        verdict="escalated",
    )
    # Broken/half files must not crash or affect the paired-task count.
    _write_doc(
        bc,
        bc.lane_processed("A-to-B") / "task-broken.md",
        {"created": "not-a-date"},
    )
    (bc.lane_processed("A-to-B") / "result-half.md").write_text(
        "---\ncreated: 2026-06-11T10:00:00\n",
        encoding="utf-8",
    )
    before = _snapshot_files(root)

    metrics = bm.compute_metrics()

    assert metrics["count"] == 3
    assert metrics["verdict_counts"] == {
        "accepted": 1,
        "escalated": 1,
        "rejected": 1,
    }
    assert metrics["durchlaufzeit_min"] == 300
    assert metrics["durchlaufzeit_median"] == 900
    assert metrics["durchlaufzeit_max"] == 1200
    assert metrics["lanes"]["A-to-B"]["count"] == 2
    assert metrics["lanes"]["B-to-A"]["verdict_counts"] == {"escalated": 1}
    assert _snapshot_files(root) == before


def test_compute_metrics_can_filter_one_lane() -> None:
    _fresh_bridge()
    bc, bm = _reload()
    _write_pair(
        bc,
        "A-to-B",
        task_id="20260611-100000-000001-0-aaaa",
        task_created="2026-06-11T10:00:00",
        result_created="2026-06-11T10:02:00",
        verdict="accepted",
    )
    _write_pair(
        bc,
        "B-to-A",
        task_id="20260611-100000-000002-0-bbbb",
        task_created="2026-06-11T10:00:00",
        result_created="2026-06-11T10:03:00",
        verdict="rejected",
    )

    metrics = bm.compute_metrics(lane="B-to-A")

    assert metrics["count"] == 1
    assert metrics["verdict_counts"] == {"rejected": 1}
    assert metrics["durchlaufzeit_min"] == 180
    assert list(metrics["lanes"]) == ["B-to-A"]


def test_write_report_only_writes_inside_state_dir() -> None:
    root = _fresh_bridge()
    bc, bm = _reload()
    _write_pair(
        bc,
        "A-to-B",
        task_id="20260611-100000-000001-0-aaaa",
        task_created="2026-06-11T10:00:00",
        result_created="2026-06-11T10:01:00",
        verdict="accepted",
    )
    state_dir = Path(os.environ["DUAL_BRIDGE_STATE"])
    outside = root / "outside-report.jsonl"

    report_path = bm.write_report(state_dir / "metrics.jsonl")

    assert report_path == state_dir / "metrics.jsonl"
    payload = json.loads(report_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["count"] == 1
    assert payload["verdict_counts"] == {"accepted": 1}
    try:
        bm.write_report(outside)
    except ValueError:
        pass
    else:
        raise AssertionError("write_report must reject paths outside DUAL_BRIDGE_STATE")
    assert not outside.exists()
