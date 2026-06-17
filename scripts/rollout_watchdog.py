"""Read-only watchdog for hanging headless Codex rollout builders.

Detector invariant: scanning and JSONL parsing are deterministic and read-only.
The optional action layer is gated behind ``--execute``; default CLI runs only
emit structured logs and do not kill processes, release leases, or requeue.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import signal
import subprocess
import sys
from typing import Any


DEFAULT_STALE_SECONDS = 600
DEFAULT_MAX_REQUEUES = 3


def _utc_naive(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is not None:
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value


def _parse_time(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return _utc_naive(value)
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).replace(
                tzinfo=None
            )
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None
    if text.isdigit():
        return _parse_time(int(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _utc_naive(dt.datetime.fromisoformat(text))
    except ValueError:
        return None


def _format_time(value: dt.datetime) -> str:
    return value.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _now(value: str | None = None) -> dt.datetime:
    parsed = _parse_time(value) if value is not None else None
    if parsed is not None:
        return parsed
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def _default_sessions_root() -> str:
    return os.path.join(os.path.expanduser("~"), ".codex", "sessions")


def _sorted_scandir(path: str) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(path) as entries:
            return sorted(entries, key=lambda entry: entry.name)
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        return []


def _iter_rollout_logs(root: str):
    """Yield ``(path, mtime_ns)`` for rollout JSONL files via sorted os.scandir."""
    root = os.fspath(root)
    for entry in _sorted_scandir(root):
        try:
            if entry.is_file(follow_symlinks=False) and fnmatch.fnmatch(
                entry.name, "rollout-*.jsonl"
            ):
                yield entry.path, entry.stat(follow_symlinks=False).st_mtime_ns
        except OSError:
            continue

    for entry in _sorted_scandir(root):
        try:
            is_dir = entry.is_dir(follow_symlinks=False)
        except OSError:
            is_dir = False
        if is_dir:
            yield from _iter_rollout_logs(entry.path)


def find_latest_rollout_log(sessions_root: str | os.PathLike[str] | None = None) -> str | None:
    """Return the newest ``rollout-*.jsonl`` path, with deterministic tie-breaks."""
    root = os.fspath(sessions_root) if sessions_root is not None else _default_sessions_root()
    candidates = []
    for path, mtime_ns in _iter_rollout_logs(root):
        abs_path = os.path.abspath(path)
        candidates.append((mtime_ns, os.path.normcase(abs_path), abs_path))
    if not candidates:
        return None
    return sorted(candidates)[-1][2]


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _event_item(record: dict) -> dict:
    return _as_dict(record.get("item"))


def _event_kind(record: dict) -> str | None:
    item = _event_item(record)
    item_type = item.get("type")
    if item_type in {"function_call", "function_call_output"}:
        return str(item_type)
    record_type = record.get("type")
    if record_type in {"function_call", "function_call_output"}:
        return str(record_type)
    return None


def _extract_call_id(record: dict, kind: str) -> str:
    item = _event_item(record)
    objects = [item, record, _as_dict(item.get("function")), _as_dict(record.get("function"))]
    keys = ("call_id", "id") if kind == "function_call" else ("call_id", "id")
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if value:
                return str(value)
    return ""


def _extract_name(record: dict) -> str:
    item = _event_item(record)
    for obj in (item, record, _as_dict(item.get("function")), _as_dict(record.get("function"))):
        value = obj.get("name")
        if value:
            return str(value)
    return ""


def _extract_timestamp(record: dict) -> tuple[str | None, dt.datetime | None]:
    item = _event_item(record)
    for obj in (record, item):
        for key in ("timestamp", "created_at", "created", "time"):
            if key in obj:
                raw = obj.get(key)
                return (None if raw is None else str(raw), _parse_time(raw))
    return None, None


def _unknown(
    *,
    sessions_root: str,
    latest_log: str | None,
    stale_seconds: int,
    now_value: dt.datetime,
    reason: str,
    parse_errors: int = 0,
    function_call_count: int = 0,
    function_call_output_count: int = 0,
) -> dict:
    return {
        "status": "unknown",
        "hanging": False,
        "reason": reason,
        "sessions_root": os.path.abspath(sessions_root),
        "latest_log": latest_log,
        "stale_seconds": int(stale_seconds),
        "now": _format_time(now_value),
        "idle_seconds": None,
        "last_call": None,
        "open_call_count": 0,
        "function_call_count": function_call_count,
        "function_call_output_count": function_call_output_count,
        "parse_errors": parse_errors,
    }


def _parse_rollout_log(path: str) -> dict:
    calls_by_id: dict[str, dict] = {}
    call_order: list[str] = []
    output_ids: set[str] = set()
    parse_errors = 0
    function_call_count = 0
    function_call_output_count = 0

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(record, dict):
                    continue

                kind = _event_kind(record)
                if kind == "function_call":
                    function_call_count += 1
                    call_id = _extract_call_id(record, kind) or f"line:{line_no}"
                    timestamp_raw, timestamp = _extract_timestamp(record)
                    calls_by_id[call_id] = {
                        "call_id": call_id,
                        "name": _extract_name(record),
                        "timestamp": timestamp_raw,
                        "_timestamp_dt": timestamp,
                        "line": line_no,
                        "path": os.path.abspath(path),
                    }
                    call_order.append(call_id)
                elif kind == "function_call_output":
                    function_call_output_count += 1
                    call_id = _extract_call_id(record, kind)
                    if call_id:
                        output_ids.add(call_id)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return {
            "unreadable": True,
            "error": f"{type(exc).__name__}: {exc}",
            "parse_errors": parse_errors,
            "function_call_count": function_call_count,
            "function_call_output_count": function_call_output_count,
            "open_calls": [],
        }

    open_calls = [
        calls_by_id[call_id]
        for call_id in call_order
        if call_id not in output_ids and call_id in calls_by_id
    ]
    return {
        "unreadable": False,
        "parse_errors": parse_errors,
        "function_call_count": function_call_count,
        "function_call_output_count": function_call_output_count,
        "open_calls": open_calls,
    }


def _public_call(call: dict) -> dict:
    return {
        "call_id": call.get("call_id", ""),
        "name": call.get("name", ""),
        "timestamp": call.get("timestamp"),
        "line": call.get("line", 0),
        "path": call.get("path", ""),
    }


def detect_hanging_builder(
    *,
    sessions_root: str | os.PathLike[str] | None = None,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    now: str | dt.datetime | None = None,
) -> dict:
    """Detect the newest unpaired function_call in the latest rollout log.

    The function never writes and never starts subprocesses. Broken JSONL lines
    are counted and skipped; a half-written log cannot crash the detector.
    """
    root = os.fspath(sessions_root) if sessions_root is not None else _default_sessions_root()
    now_value = _now(now if isinstance(now, str) else None)
    if isinstance(now, dt.datetime):
        now_value = _utc_naive(now)

    latest_log = find_latest_rollout_log(root)
    if latest_log is None:
        return _unknown(
            sessions_root=root,
            latest_log=None,
            stale_seconds=stale_seconds,
            now_value=now_value,
            reason="no_rollout_logs",
        )

    parsed = _parse_rollout_log(latest_log)
    common = {
        "sessions_root": os.path.abspath(root),
        "latest_log": os.path.abspath(latest_log),
        "stale_seconds": int(stale_seconds),
        "now": _format_time(now_value),
        "function_call_count": parsed["function_call_count"],
        "function_call_output_count": parsed["function_call_output_count"],
        "parse_errors": parsed["parse_errors"],
    }
    if parsed.get("unreadable"):
        out = _unknown(
            sessions_root=root,
            latest_log=os.path.abspath(latest_log),
            stale_seconds=stale_seconds,
            now_value=now_value,
            reason="unreadable_log",
            parse_errors=parsed["parse_errors"],
            function_call_count=parsed["function_call_count"],
            function_call_output_count=parsed["function_call_output_count"],
        )
        out["error"] = parsed.get("error", "")
        return out

    if parsed["function_call_count"] == 0:
        return _unknown(
            sessions_root=root,
            latest_log=os.path.abspath(latest_log),
            stale_seconds=stale_seconds,
            now_value=now_value,
            reason="no_function_calls",
            parse_errors=parsed["parse_errors"],
            function_call_count=parsed["function_call_count"],
            function_call_output_count=parsed["function_call_output_count"],
        )

    open_calls = parsed["open_calls"]
    if not open_calls:
        return {
            **common,
            "status": "ok",
            "hanging": False,
            "reason": "all_function_calls_completed",
            "idle_seconds": None,
            "last_call": None,
            "open_call_count": 0,
        }

    last_call = open_calls[-1]
    timestamp = last_call.get("_timestamp_dt")
    if timestamp is None:
        return {
            **common,
            "status": "unknown",
            "hanging": False,
            "reason": "last_call_without_timestamp",
            "idle_seconds": None,
            "last_call": _public_call(last_call),
            "open_call_count": len(open_calls),
        }

    idle_seconds = max(0, int((now_value - timestamp).total_seconds()))
    is_hanging = idle_seconds >= int(stale_seconds)
    return {
        **common,
        "status": "hanging" if is_hanging else "pending",
        "hanging": is_hanging,
        "reason": (
            "last_function_call_stale"
            if is_hanging
            else "last_function_call_waiting_for_output"
        ),
        "idle_seconds": idle_seconds,
        "last_call": _public_call(last_call),
        "open_call_count": len(open_calls),
    }


def _kill_process_tree(pid: int) -> None:
    """Kill pid and descendants. Best-effort; exceptions are swallowed."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
            )
        else:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
    except Exception:
        pass


def plan_actions(
    result: dict,
    *,
    pid: int | None,
    lease_file: str | os.PathLike[str] | None,
    requeue_log: str | os.PathLike[str] | None,
    requeue_count: int,
    max_requeues: int = DEFAULT_MAX_REQUEUES,
) -> dict:
    """Build a deterministic action plan for a hanging builder result."""
    planned: list[dict] = []
    if not result.get("hanging"):
        return {"needed": False, "planned": planned}

    if pid is not None:
        planned.append({"kind": "kill_process_tree", "pid": int(pid)})
    else:
        planned.append(
            {"kind": "kill_process_tree", "status": "skipped", "reason": "missing_pid"}
        )

    if lease_file is not None:
        planned.append({"kind": "release_lease", "path": os.fspath(lease_file)})
    else:
        planned.append(
            {"kind": "release_lease", "status": "skipped", "reason": "missing_lease_file"}
        )

    if int(requeue_count) >= int(max_requeues):
        planned.append(
            {
                "kind": "escalate_owner",
                "reason": "max_requeues_reached",
                "requeue_count": int(requeue_count),
                "max_requeues": int(max_requeues),
            }
        )
    else:
        planned.append(
            {
                "kind": "requeue",
                "path": os.fspath(requeue_log) if requeue_log is not None else None,
                "next_requeue_count": int(requeue_count) + 1,
                "max_requeues": int(max_requeues),
            }
        )

    return {"needed": True, "planned": planned}


def _append_jsonl(path: str, payload: dict) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def apply_actions(plan: dict, *, execute: bool, result: dict) -> dict:
    """Apply or dry-run an action plan. Default callers pass execute=False."""
    action = {
        "execute": bool(execute),
        "needed": bool(plan.get("needed")),
        "planned": list(plan.get("planned") or []),
        "results": [],
    }
    for item in action["planned"]:
        kind = item.get("kind")
        record = {"kind": kind, "executed": False, "status": "dry_run"}
        if not execute:
            action["results"].append(record)
            continue

        try:
            if kind == "kill_process_tree" and item.get("pid") is not None:
                _kill_process_tree(int(item["pid"]))
                record.update({"executed": True, "status": "attempted"})
            elif kind == "release_lease" and item.get("path"):
                path = os.fspath(item["path"])
                if os.path.exists(path):
                    os.remove(path)
                    status = "removed"
                else:
                    status = "missing"
                record.update({"executed": True, "status": status, "path": path})
            elif kind in {"requeue", "escalate_owner"} and item.get("path"):
                payload = {
                    "event": kind,
                    "last_call": result.get("last_call"),
                    "idle_seconds": result.get("idle_seconds"),
                    "item": item,
                }
                _append_jsonl(os.fspath(item["path"]), payload)
                record.update({"executed": True, "status": "written", "path": item["path"]})
            elif kind == "escalate_owner":
                record.update({"executed": True, "status": "logged"})
            else:
                record.update({"status": item.get("status", "skipped")})
        except Exception as exc:  # noqa: BLE001 - watchdog action logging must continue
            record.update(
                {"executed": False, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
            )
        action["results"].append(record)
    return action


def render_text(payload: dict) -> str:
    result = payload.get("result", {})
    lines = ["=== dual-bridge Rollout-Watchdog ==="]
    lines.append(
        f"status={result.get('status')} hanging={result.get('hanging')} "
        f"idle_seconds={result.get('idle_seconds')}"
    )
    if result.get("latest_log"):
        lines.append(f"log={result.get('latest_log')}")
    if result.get("last_call"):
        call = result["last_call"]
        lines.append(
            f"last_call={call.get('call_id')} name={call.get('name')} "
            f"line={call.get('line')} timestamp={call.get('timestamp')}"
        )
    lines.append(
        f"execute={payload.get('action', {}).get('execute')} "
        f"actions={len(payload.get('action', {}).get('planned') or [])}"
    )
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect hanging headless Codex builders from rollout JSONL logs."
    )
    parser.add_argument("--sessions-root", default=_default_sessions_root())
    parser.add_argument("--stale-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--now", default=None, help="ISO timestamp for deterministic tests.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--execute", action="store_true", help="Enable real action effects.")
    parser.add_argument("--pid", type=int, default=None, help="Builder root PID to kill.")
    parser.add_argument("--lease-file", default=None, help="Lease file to remove on execute.")
    parser.add_argument("--requeue-log", default=None, help="JSONL action log for requeue.")
    parser.add_argument("--requeue-count", type=int, default=0)
    parser.add_argument("--max-requeues", type=int, default=DEFAULT_MAX_REQUEUES)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = detect_hanging_builder(
        sessions_root=args.sessions_root,
        stale_seconds=args.stale_seconds,
        now=args.now,
    )
    plan = plan_actions(
        result,
        pid=args.pid,
        lease_file=args.lease_file,
        requeue_log=args.requeue_log,
        requeue_count=args.requeue_count,
        max_requeues=args.max_requeues,
    )
    action = apply_actions(plan, execute=args.execute, result=result)
    payload = {"result": result, "action": action}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(payload))
    return 1 if result.get("hanging") else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
