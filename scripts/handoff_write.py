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
    args = parser.parse_args(argv)

    bc.ensure_dirs()

    task_id = bc.make_task_id()
    created = bc.now_iso()
    frontmatter = {
        "created": created,
        "agent": f"laptop-a-claude@{bc.DEVICE}",
        "target_agent": args.target,
        "purpose": "handoff",
        "status": "open",
        "task_id": task_id,
        "kind": args.kind,
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
        "<wird von Laptop B gefüllt>\n"
    )
    doc = bc.build_document(frontmatter, body)

    out_path = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(out_path, doc)

    print(f"[A] Task geschrieben: {out_path.name}")
    print(f"    task_id = {task_id}")
    print(f"    kind    = {args.kind}")
    print(f"    status  = open  →  warte auf Laptop B (inbox/result-{task_id}.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
