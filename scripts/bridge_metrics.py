"""Read-only metrics over processed dual-bridge lane archives.

Scans lane _processed/ folders for task/result pairs and computes verdict
counts plus task throughput durations. It never writes to lane trees.

CLI:
    python bridge_metrics.py [--format text|json] [--lane <lane>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
from pathlib import Path

import bridge_common as bc


def _resolve_state_dir() -> Path:
    override = os.environ.get("DUAL_BRIDGE_STATE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "state"


STATE_DIR = _resolve_state_dir()


def _all_lanes() -> list[str]:
    lanes: list[str] = []
    for cfg in bc.ENDPOINTS.values():
        lane = cfg.get("sends_on")
        if lane and lane not in lanes:
            lanes.append(lane)
    return lanes or ["A-to-B", "B-to-A"]


def _safe_frontmatter(path: Path) -> dict:
    try:
        fm, _body = bc.parse_frontmatter(bc.read_text_utf8(path))
        return fm
    except Exception:  # noqa: BLE001 - metrics must never crash on one file
        return {}


def _task_id_from_name(name: str, prefix: str) -> str:
    stem = name
    if stem.endswith(".md"):
        stem = stem[:-3]
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    if ".claimed-" in stem:
        stem = stem.split(".claimed-", 1)[0]
    return stem


def _parse_time(value) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo:
            return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _finalize_metrics(count: int, verdict_counts: dict[str, int],
                      durations: list[int], skipped_files: int,
                      skipped_pairs: int) -> dict:
    out = {
        "count": count,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "durchlaufzeit_min": min(durations) if durations else None,
        "durchlaufzeit_median": statistics.median(durations) if durations else None,
        "durchlaufzeit_max": max(durations) if durations else None,
        "skipped_files": skipped_files,
        "skipped_pairs": skipped_pairs,
    }
    median = out["durchlaufzeit_median"]
    if isinstance(median, float) and median.is_integer():
        out["durchlaufzeit_median"] = int(median)
    return out


def _collect_lane(lane: str) -> tuple[dict, list[int]]:
    processed = bc.lane_processed(lane)
    tasks: dict[str, dict] = {}
    results: dict[str, dict] = {}
    skipped_files = 0

    try:
        files = sorted(p for p in processed.iterdir() if p.is_file())
    except (FileNotFoundError, NotADirectoryError, OSError):
        files = []

    for path in files:
        name = path.name
        if name.startswith("task-"):
            fm = _safe_frontmatter(path)
            task_id = fm.get("task_id") or _task_id_from_name(name, "task-")
            if not task_id or not fm.get("created"):
                skipped_files += 1
                continue
            tasks[task_id] = fm
        elif name.startswith("result-"):
            fm = _safe_frontmatter(path)
            task_id = fm.get("task_id") or _task_id_from_name(name, "result-")
            if not task_id:
                skipped_files += 1
                continue
            results[task_id] = fm

    count = 0
    verdict_counts: dict[str, int] = {}
    durations: list[int] = []
    skipped_pairs = 0

    for task_id, task_fm in sorted(tasks.items()):
        result_fm = results.get(task_id)
        if not result_fm:
            skipped_pairs += 1
            continue

        verdict = str(result_fm.get("verdict") or "unknown").strip().lower() or "unknown"
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
        count += 1

        start = _parse_time(task_fm.get("created"))
        end = (
            _parse_time(result_fm.get("created"))
            or _parse_time(result_fm.get("claimed_at"))
            or _parse_time(task_fm.get("claimed_at"))
        )
        if start is None or end is None:
            skipped_pairs += 1
            continue
        durations.append(max(0, int((end - start).total_seconds())))

    return (
        _finalize_metrics(count, verdict_counts, durations, skipped_files, skipped_pairs),
        durations,
    )


def _scan_lane(lane: str) -> dict:
    return _collect_lane(lane)[0]


def compute_metrics(lane: str | None = None) -> dict:
    """Return metrics for processed task/result pairs.

    ``lane`` restricts the scan to one lane. All lane access is read-only and
    fail-soft: broken files and incomplete pairs are skipped.
    """
    lanes = [lane] if lane else _all_lanes()
    collected = {lane_name: _collect_lane(lane_name) for lane_name in lanes}
    by_lane = {lane_name: item[0] for lane_name, item in collected.items()}

    count = sum(item["count"] for item in by_lane.values())
    verdict_counts: dict[str, int] = {}
    skipped_files = 0
    skipped_pairs = 0
    all_durations: list[int] = []
    for item in by_lane.values():
        skipped_files += item.get("skipped_files", 0)
        skipped_pairs += item.get("skipped_pairs", 0)
        for verdict, n in item["verdict_counts"].items():
            verdict_counts[verdict] = verdict_counts.get(verdict, 0) + n
    for _lane_name, (_metrics, lane_durations) in collected.items():
        all_durations.extend(lane_durations)

    aggregate = _finalize_metrics(
        count, verdict_counts, all_durations, skipped_files, skipped_pairs
    )
    aggregate["lanes"] = by_lane
    return aggregate


def render_json(metrics: dict) -> str:
    return json.dumps(metrics, ensure_ascii=False, indent=2)


def render_text(metrics: dict) -> str:
    lines = ["=== dual-bridge Bridge-Metriken ==="]
    lines.append(
        f"count={metrics.get('count', 0)}  "
        f"min={metrics.get('durchlaufzeit_min')}s  "
        f"median={metrics.get('durchlaufzeit_median')}s  "
        f"max={metrics.get('durchlaufzeit_max')}s"
    )
    verdicts = metrics.get("verdict_counts") or {}
    if verdicts:
        lines.append(
            "verdicts="
            + ", ".join(f"{verdict}:{count}" for verdict, count in verdicts.items())
        )
    else:
        lines.append("verdicts=-")
    for lane, item in (metrics.get("lanes") or {}).items():
        lines.append(
            f"lane-{lane}: count={item.get('count', 0)}  "
            f"skipped_files={item.get('skipped_files', 0)}  "
            f"skipped_pairs={item.get('skipped_pairs', 0)}"
        )
    return "\n".join(lines) + "\n"


def _path_inside_state(path: Path) -> Path:
    state = STATE_DIR.resolve()
    target = path if path.is_absolute() else state / path
    target = target.resolve()
    try:
        target.relative_to(state)
    except ValueError:
        raise ValueError(f"Report path must stay inside local state dir: {state}") from None
    return target


def write_report(path, lane: str | None = None, *, fmt: str = "json") -> Path:
    """Write one report file under STATE_DIR only and return its path."""
    target = _path_inside_state(Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    metrics = compute_metrics(lane=lane)
    if fmt == "text":
        content = render_text(metrics)
    else:
        content = json.dumps(metrics, ensure_ascii=False) + "\n"
    target.write_text(content, encoding="utf-8", newline="\n")
    return target


def _parse_args(argv: list | None):
    parser = argparse.ArgumentParser(
        description="Read-only Bridge-Metriken aus lane _processed/."
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--lane", default=None, help="Nur diese Lane auswerten.")
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    args = _parse_args(argv)
    metrics = compute_metrics(lane=args.lane)
    print(render_json(metrics) if args.format == "json" else render_text(metrics))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
