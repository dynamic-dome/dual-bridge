"""Write a bridge task into this endpoint's send-lane outbox.

Usage:
    python handoff_write.py "Auftragstext"
    python handoff_write.py --kind implement --adapter codex --repo <url> "..."
    python handoff_write.py --adapter claude --to claude@laptop-a "..."

The task is written into lane-<send_lane>/outbox/ of THIS endpoint
(DUAL_BRIDGE_ENDPOINT). `--adapter` selects which runner the receiver uses
(echo/codex/claude); `--to` overrides the target endpoint (default: the peer).
"""
from __future__ import annotations

import argparse
import sys

import bridge_common as bc
import secret_gate


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
                        choices=["echo", "codex", "claude", "increment"],
                        help="Which runner the receiver should use.")
    parser.add_argument("--to", default="",
                        help="Target endpoint (default: the peer of my endpoint).")
    parser.add_argument("--allow-secrets", action="store_true",
                        help="Deliberately bypass the outgoing secrets gate.")
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
    document = bc.build_document(frontmatter, body)
    if not args.allow_secrets:
        findings = secret_gate.scan_text(document)
        if findings:
            print("[Secrets-Gate] Task blockiert: moegliche Secrets gefunden.", file=sys.stderr)
            for finding in findings:
                print(
                    "[Secrets-Gate] "
                    f"{finding['kind']} at line {finding['line']}, col {finding['col']}: "
                    f"{finding['redacted']}",
                    file=sys.stderr,
                )
            return 2
    out_path = bc.lane_outbox(lane) / f"task-{task_id}.md"
    bc.write_text_utf8(out_path, document)
    print(f"[{me}] Task → lane-{lane}/outbox/{out_path.name} (adapter={args.adapter}, to={to})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
