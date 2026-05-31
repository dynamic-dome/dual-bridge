"""Collect results from this endpoint's receive-lane inbox.

Usage:
    python handoff_collect.py            # show new results, archive them
    python handoff_collect.py --peek     # show without archiving
    python handoff_collect.py --watch    # loop until a result arrives

Reads result-*.md from THIS endpoint's inbox/ (DUAL_BRIDGE_ENDPOINT),
prints them, then moves them into _processed/ (no delete — manifest rule 7).
In --peek mode nothing is moved.
"""
from __future__ import annotations

import argparse
import sys
import time

import bridge_common as bc


def _is_conflict_copy(name: str) -> bool:
    return "(" in name and ")" in name


def show_result(path: bc.Path) -> None:
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(path))
    print("=" * 60)
    print(f"RESULT  {path.name}")
    print(f"  task_id   : {fm.get('task_id', '?')}")
    print(f"  from      : {fm.get('agent', '?')}")
    print(f"  status    : {fm.get('status', '?')}")
    print(f"  created   : {fm.get('created', '?')}")
    branch = fm.get("branch", "")
    commit = fm.get("commit", "")
    if branch:
        print(f"  branch    : {branch}  (commit {commit or '?'})")
    print("-" * 60)
    print(body.rstrip())
    if fm.get("status") == "done" and branch:
        print("-" * 60)
        print(f"→ Hol das Artefakt auf A:  git fetch && git checkout {branch}")
    elif fm.get("status") == "error":
        print("-" * 60)
        print("→ FEHLER-Result — siehe ## FEHLER oben.")
    print("=" * 60)


def collect_once(peek: bool) -> int:
    bc.ensure_dirs()
    me = bc.this_endpoint()
    lane = bc.send_lane()
    results = sorted(bc.lane_inbox(lane).glob("result-*.md"))
    n = 0
    for path in results:
        if _is_conflict_copy(path.name):
            print(f"[{me}] Drive-Conflict-Copy ignoriert: {path.name}")
            continue
        show_result(path)
        n += 1
        if not peek:
            dest = bc.lane_processed(lane) / path.name
            try:
                path.replace(dest)
            except OSError:
                print(f"[{me}] Archivieren fehlgeschlagen für {path.name} (Lock?).")
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect bridge results for this endpoint.")
    parser.add_argument(
        "--peek", action="store_true", help="Show without archiving to _processed/."
    )
    parser.add_argument("--watch", action="store_true", help="Loop until a result arrives.")
    parser.add_argument("--interval", type=int, default=10, help="Watch poll seconds.")
    args = parser.parse_args(argv)

    me = bc.this_endpoint()
    print(f"[{me}] Bridge-Root: {bc.bridge_root()}")

    if not args.watch:
        n = collect_once(peek=args.peek)
        if n == 0:
            print(f"[{me}] Keine neuen Results im inbox/.")
        else:
            print(f"[{me}] {n} Result(s) {'angezeigt' if args.peek else 'eingesammelt'}.")
        return 0

    print(f"[{me}] Watch-Modus, alle {args.interval}s. Strg+C zum Beenden.")
    try:
        while True:
            n = collect_once(peek=args.peek)
            if n:
                print(f"[{me}] {n} Result(s) eingesammelt.")
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(f"\n[{me}] Beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
