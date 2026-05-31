"""Stage 0 — Laptop A: write a task into the bridge outbox.

Usage:
    python handoff_write.py "Dein Auftragstext"
    python handoff_write.py --kind echo "Echo this please"

Stage 0 default kind is `echo`: Laptop B will not run any LLM, it just echoes
the task body back. This proves the transport + schema + Drive roundtrip.
"""
from __future__ import annotations

import argparse
import sys

import bridge_common as bc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a bridge task (Laptop A).")
    parser.add_argument("text", help="The task / instruction text for Laptop B.")
    parser.add_argument(
        "--kind",
        default="echo",
        choices=["echo", "implement", "research", "review", "test"],
        help="Task kind. Stage 0 uses 'echo'.",
    )
    parser.add_argument(
        "--target",
        default="laptop-b-worker",
        help="Target agent label (default: laptop-b-worker).",
    )
    parser.add_argument(
        "--repo", default="",
        help="Git repo (URL or local path on B) for codex to work in (LLM kinds).",
    )
    parser.add_argument(
        "--base-branch", default="main",
        help="Base branch to start from (default: main).",
    )
    parser.add_argument("--adapter", default="echo",
                        choices=["echo", "codex", "claude"],
                        help="Which runner the receiver should use.")
    parser.add_argument("--to", default="",
                        help="Target endpoint (default: the peer of my endpoint).")
    args = parser.parse_args(argv)

    bc.ensure_dirs()
    lane = bc.send_lane()
    me = bc.this_endpoint()
    # default `to` = the receiver of my send lane
    to = args.to or next((ep for ep, cfg in bc.ENDPOINTS.items()
                          if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    frontmatter = {
        "created": bc.now_iso(),
        "schema_version": "2",
        "agent": me,
        "from": me,
        "to": to,
        "target_agent": args.target,
        "purpose": "handoff",
        "status": "open",
        "task_id": task_id,
        "kind": args.kind,
        "adapter": args.adapter,
        "repo": args.repo,
        "base_branch": args.base_branch,
        "claimed_by": "",
        "claimed_at": "",
    }
    body = (
        "## Auftrag\n"
        f"{args.text}\n\n"
        "## Akzeptanzkriterien\n"
        "- [ ] Ergebnis liegt im inbox/ mit demselben task_id\n\n"
        "## Ergebnis\n"
        "<wird vom Empfänger gefüllt>\n"
    )
    out_path = bc.lane_outbox(lane) / f"task-{task_id}.md"
    bc.write_text_utf8(out_path, bc.build_document(frontmatter, body))
    print(f"[{me}] Task → lane-{lane}/outbox/{out_path.name} (adapter={args.adapter}, to={to})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
