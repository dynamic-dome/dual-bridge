"""Tests for the read-only lane health checker (bridge_health.py).

Dual-runnable like the rest of the suite:
    python -m pytest scripts/test_bridge_health.py

The checker must reuse bridge_status' lane scan and must never mutate lane
files. The autouse conftest fixture isolates DUAL_BRIDGE_ROOT to tmp storage.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path


def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-health-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_status as bs
    importlib.reload(bs)
    import bridge_health as bh
    importlib.reload(bh)
    return bc, bs, bh


def _write_task(
    bc,
    lane: str,
    *,
    task_id: str,
    status: str = "open",
    created: str = "2026-06-11T12:00:00",
    claimed: str | None = None,
) -> Path:
    bc.ensure_dirs()
    fm = {
        "created": created,
        "schema_version": "2",
        "agent": "claude@laptop-a",
        "from": "claude@laptop-a",
        "to": "codex@laptop-b",
        "purpose": "handoff",
        "status": status,
        "task_id": task_id,
        "kind": "implement",
        "adapter": "codex",
    }
    name = (
        f"task-{task_id}.claimed-{claimed}-abcd1234.md"
        if claimed
        else f"task-{task_id}.md"
    )
    path = bc.lane_outbox(lane) / name
    bc.write_text_utf8(path, bc.build_document(fm, "## Auftrag\nmach was\n"))
    return path


def _snapshot_files(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size)
        for p in root.rglob("*")
        if p.is_file()
    }


def test_fresh_open_task_has_no_finding_and_is_read_only() -> None:
    root = _fresh_bridge()
    bc, _bs, bh = _reload()
    _write_task(
        bc,
        "A-to-B",
        task_id="20260611-115930-000000-0-fresh",
        created="2026-06-11T11:59:30",
    )
    before = _snapshot_files(root)

    findings = bh.check_lane_health(
        now="2026-06-11T12:00:00",
        max_age_s=120,
        max_errors=0,
    )

    assert findings == []
    assert _snapshot_files(root) == before


def test_overaged_oldest_open_task_reports_lane_finding() -> None:
    _fresh_bridge()
    bc, _bs, bh = _reload()
    _write_task(
        bc,
        "A-to-B",
        task_id="20260611-110000-000000-0-old1",
        created="2026-06-11T11:00:00",
    )
    _write_task(
        bc,
        "A-to-B",
        task_id="20260611-115930-000000-0-new1",
        created="2026-06-11T11:59:30",
    )

    findings = bh.check_lane_health(
        now="2026-06-11T12:00:00",
        max_age_s=1800,
        max_errors=99,
    )

    assert len(findings) == 1
    assert findings[0]["lane"] == "A-to-B"
    assert findings[0]["reason"] == "oldest_open_task_too_old"
    assert findings[0]["oldest_open_task_id"] == "20260611-110000-000000-0-old1"
    assert findings[0]["oldest_open_age_s"] == 3600
    assert findings[0]["open_count"] == 2


def test_lane_errors_above_threshold_reports_finding() -> None:
    _fresh_bridge()
    bc, _bs, bh = _reload()
    bc.ensure_dirs()
    bc.lane_errors("B-to-A").mkdir(parents=True, exist_ok=True)
    bc.write_text_utf8(bc.lane_errors("B-to-A") / "task-bad.md", "x")
    bc.write_text_utf8(bc.lane_errors("B-to-A") / "task-bad2.md", "x")

    findings = bh.check_lane_health(
        now="2026-06-11T12:00:00",
        max_age_s=3600,
        max_errors=1,
    )

    assert len(findings) == 1
    assert findings[0]["lane"] == "B-to-A"
    assert findings[0]["reason"] == "lane_errors_above_threshold"
    assert findings[0]["errors_count"] == 2
    assert findings[0]["max_errors"] == 1


def test_cli_json_returns_one_when_findings(capsys) -> None:
    _fresh_bridge()
    bc, _bs, bh = _reload()
    _write_task(
        bc,
        "A-to-B",
        task_id="20260611-110000-000000-0-old1",
        created="2026-06-11T11:00:00",
    )

    rc = bh.main(["--format", "json", "--now", "2026-06-11T12:00:00", "--max-age-s", "60"])

    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["lane"] == "A-to-B"
