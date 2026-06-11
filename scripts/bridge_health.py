"""Read-only lane health checks for dual-bridge.

This module is a narrow health lens on top of bridge_status' existing lane
scanner. It never writes, claims, moves, deletes, or creates bridge files.

CLI:
    python bridge_health.py [--format text|json]

Exit code is 0 when lanes are healthy and 1 when health findings exist.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys

import bridge_common as bc
import bridge_status


DEFAULT_MAX_AGE_S = 3600
DEFAULT_MAX_ERRORS = 0

_TASK_ID_TS_RE = re.compile(r"^(?P<date>\d{8})-(?P<time>\d{6})-")


def _default_max_age_s() -> int:
    return bc.config_value(
        "lane_health_max_age_s",
        "DUAL_BRIDGE_LANE_HEALTH_MAX_AGE_S",
        DEFAULT_MAX_AGE_S,
        int,
    )


def _default_max_errors() -> int:
    return bc.config_value(
        "lane_health_max_errors",
        "DUAL_BRIDGE_LANE_HEALTH_MAX_ERRORS",
        DEFAULT_MAX_ERRORS,
        int,
    )


def _parse_time(value) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _task_created_at(task) -> dt.datetime | None:
    match = _TASK_ID_TS_RE.match(str(getattr(task, "task_id", "")))
    if match:
        raw = f"{match.group('date')}{match.group('time')}"
        try:
            return dt.datetime.strptime(raw, "%Y%m%d%H%M%S")
        except ValueError:
            pass
    return _parse_time(getattr(task, "created", ""))


def _all_lanes() -> list[str]:
    fn = getattr(bridge_status, "_all_lanes", None)
    if callable(fn):
        return list(fn())
    lanes: list[str] = []
    for cfg in bc.ENDPOINTS.values():
        lane = cfg.get("sends_on")
        if lane and lane not in lanes:
            lanes.append(lane)
    return lanes or ["A-to-B", "B-to-A"]


def _base_finding(lane_status, max_age_s: int, max_errors: int) -> dict:
    return {
        "lane": lane_status.lane,
        "open_count": len(lane_status.open),
        "claimed_count": len(lane_status.claimed),
        "errors_count": lane_status.errors_count,
        "max_age_s": max_age_s,
        "max_errors": max_errors,
    }


def check_lane_health(now=None, max_age_s: int | None = None,
                      max_errors: int | None = None) -> list:
    """Return health findings per lane, using bridge_status.scan_lane().

    Findings are emitted when the oldest open task is older than max_age_s or
    when a lane's _errors/ count is above max_errors. This function is strictly
    read-only because it delegates lane inspection to bridge_status.scan_lane().
    """
    current = _parse_time(now) or dt.datetime.now()
    max_age_s = _default_max_age_s() if max_age_s is None else int(max_age_s)
    max_errors = _default_max_errors() if max_errors is None else int(max_errors)

    findings: list[dict] = []
    for lane in _all_lanes():
        lane_status = bridge_status.scan_lane(lane)

        oldest_task = None
        oldest_created = None
        for task in lane_status.open:
            created_at = _task_created_at(task)
            if created_at is None:
                continue
            if oldest_created is None or created_at < oldest_created:
                oldest_created = created_at
                oldest_task = task

        if oldest_created is not None:
            age_s = max(0, int((current - oldest_created).total_seconds()))
            if age_s > max_age_s:
                finding = _base_finding(lane_status, max_age_s, max_errors)
                finding.update({
                    "reason": "oldest_open_task_too_old",
                    "oldest_open_task_id": getattr(oldest_task, "task_id", ""),
                    "oldest_open_created": oldest_created.isoformat(),
                    "oldest_open_age_s": age_s,
                })
                findings.append(finding)

        if lane_status.errors_count > max_errors:
            finding = _base_finding(lane_status, max_age_s, max_errors)
            finding.update({
                "reason": "lane_errors_above_threshold",
            })
            findings.append(finding)

    return findings


def render_json(findings: list) -> str:
    return json.dumps({"findings": findings}, ensure_ascii=False, indent=2)


def render_text(findings: list) -> str:
    lines: list[str] = ["=== dual-bridge Lane-Health ==="]
    if not findings:
        lines.append("OK - keine Lane-Health-Findings.")
        return "\n".join(lines) + "\n"

    for finding in findings:
        reason = finding.get("reason", "?")
        lane = finding.get("lane", "?")
        lines.append(f"!! {lane}: {reason}")
        lines.append(
            f"   open={finding.get('open_count', 0)}  "
            f"claimed={finding.get('claimed_count', 0)}  "
            f"errors={finding.get('errors_count', 0)}"
        )
        if reason == "oldest_open_task_too_old":
            lines.append(
                f"   oldest={finding.get('oldest_open_task_id', '?')}  "
                f"age_s={finding.get('oldest_open_age_s', '?')}  "
                f"max_age_s={finding.get('max_age_s', '?')}"
            )
        elif reason == "lane_errors_above_threshold":
            lines.append(f"   max_errors={finding.get('max_errors', '?')}")
    return "\n".join(lines) + "\n"


def _parse_args(argv: list | None):
    parser = argparse.ArgumentParser(
        description="Read-only Lane-Health-Check fuer dual-bridge."
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-age-s", type=int, default=None)
    parser.add_argument("--max-errors", type=int, default=None)
    parser.add_argument(
        "--now",
        default=None,
        help="Test-/Debug-Zeitpunkt als ISO-String; Default ist aktuelle Zeit.",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    args = _parse_args(argv)
    findings = check_lane_health(
        now=args.now,
        max_age_s=args.max_age_s,
        max_errors=args.max_errors,
    )
    out = render_json(findings) if args.format == "json" else render_text(findings)
    print(out)
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
