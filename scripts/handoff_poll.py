"""Stage 0 — Laptop B: poll the outbox, claim open tasks, echo a result.

Usage:
    python handoff_poll.py            # one pass, process all open tasks
    python handoff_poll.py --watch    # loop forever, polling every N seconds
    python handoff_poll.py --watch --interval 10

Stage 0 behaviour: for each `open` task, claim it atomically, write a Dummy
echo result into inbox/, then move the task into _processed/ (never delete —
manifest rule 7). No LLM is called yet; that is Stage 1.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import bridge_common as bc
import runners  # noqa: F401 -- registers echo
import codex_adapter  # noqa: F401 -- registers codex
import claude_adapter  # noqa: F401 -- registers claude

CODEX_WORKROOT = bc.Path(
    os.environ.get("DUAL_BRIDGE_WORKROOT") or (bc.Path.home() / "dual-bridge-work")
)

# GT1: gate-evidence fields that are mirrored verbatim from a task's frontmatter
# into the result's frontmatter when present. The later gate needs gate_id/run_id/
# stage threaded through the echo path. Mirroring is additive and absent-safe.
MIRROR_FIELDS = ("gate_id", "run_id", "stage", "loop_id", "round")


def _is_conflict_copy(name: str) -> bool:
    """Google-Drive conflict copies look like 'task-... (1).md'. Skip them."""
    return "(" in name and ")" in name


def parse_verdict(text: str) -> tuple[str, str]:
    """Extract a review verdict from a reviewer's answer (Stage-2b core).

    Convention: the reviewer ends with a line `VERDICT: accepted`,
    `VERDICT: escalate`, or `VERDICT: rejected` (case-insensitive; the LAST
    such line wins). Returns (verdict, reason).

    FAIL-CLOSED (PFLICHT): no marker, empty text, or any unrecognised verdict
    token resolves to ("rejected", <reason>). A review NEVER auto-accepts on
    ambiguity — only an explicit `accepted` marker yields "accepted".
    """
    if not text or not text.strip():
        return ("rejected", "empty reviewer answer")
    found: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("verdict:"):
            found = stripped.split(":", 1)[1].strip().lower()
    if found is None:
        return ("rejected", "no VERDICT marker found")
    if found == "accepted":
        return ("accepted", "")
    if found == "escalate":
        return ("escalate", "")
    if found == "rejected":
        return ("rejected", "")
    return ("rejected", f"unrecognised verdict token: {found!r}")


def _build_result_fm(fm: dict, result, task_id: str, adapter: str) -> dict:
    """Assemble the result frontmatter from a RunnerResult. Reply goes back to
    the original sender (fm['from']); branch/commit only if the runner set them."""
    result_fm = {
        "created": bc.now_iso(),
        "agent": fm["claimed_by"],
        "from": bc.this_endpoint(),
        "to": fm.get("from", ""),
        "purpose": "handoff",
        "status": result.status,
        "task_id": task_id,
        "kind": fm.get("kind", "echo"),
        "adapter": adapter,
        "replies_to": f"task-{task_id}.md",
    }
    if result.branch:
        result_fm["branch"] = result.branch
    if result.commit:
        result_fm["commit"] = result.commit
    # Review verdict is RUNNER output (not a task echo) -> fixed path, NOT via
    # MIRROR_FIELDS. Present only when the review path set it on the result.
    if result.verdict:
        result_fm["verdict"] = result.verdict
        if result.verdict_reason:
            result_fm["verdict_reason"] = result.verdict_reason
    # GT1: thread gate-evidence fields through verbatim — only when present and
    # non-empty in the task FM (never inject an empty `gate_id: ""`).
    for k in MIRROR_FIELDS:
        if k in fm and fm[k] not in (None, ""):
            result_fm[k] = fm[k]
    # Loop envelope: a task that carries loop_id is part of a ping-pong loop.
    # Its result payload is the RUNNER OUTPUT (the next value), not the echoed
    # input. Only set when the task is a loop task AND the runner succeeded.
    if fm.get("loop_id") and result.status == "done" and result.antwort.strip():
        result_fm["payload"] = result.antwort.strip()
    return result_fm


def process_one(task_path: bc.Path, lane: str) -> bool:
    """Claim + route + run + publish a single task within `lane`. Returns True
    if a result was written."""
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(task_path))
    if fm.get("status") != "open":
        return False

    task_id = fm.get("task_id", task_path.stem.replace("task-", ""))
    # Security: the task_id reaches a result filename and a git branch name.
    # Reject anything that is not a well-formed make_task_id() to close
    # path-traversal / branch-injection via a hostile/corrupt task file.
    if not bc.is_valid_task_id(task_id):
        print(f"[{lane}] Task {task_path.name} hat ungültige task_id {task_id!r} — übersprungen.")
        return False

    to = fm.get("to", "")
    if to and to != bc.this_endpoint():
        return False

    claimed_path = bc.claim_task(task_path, bc.DEVICE)
    if claimed_path is None:
        print(f"[{lane}] Konnte {task_path.name} nicht claimen — übersprungen.")
        return False

    # Re-read from the claimed path to confirm we hold the canonical content.
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(claimed_path))
    fm["claimed_by"] = f"{bc.this_endpoint()}@{bc.DEVICE}"
    fm["claimed_at"] = bc.now_iso()

    auftrag = _extract_section(body, "## Auftrag") or body.strip()
    adapter = fm.get("adapter", "echo")
    runner = runners.RUNNERS.get(adapter)
    if runner is None:
        result = runners.RunnerResult(status="error",
                                      error_text=f"unbekannter adapter: {adapter!r}")
    else:
        try:
            result = runner(auftrag=auftrag, fm=fm, workroot=CODEX_WORKROOT)
        except Exception as exc:  # noqa: BLE001 -- a runner must never crash the poller
            result = runners.RunnerResult(status="error",
                                          error_text=f"{adapter} runner crash: {type(exc).__name__}: {exc}")

    # Stage-2b: review kind gets accepted/rejected verdict semantics. Verdict
    # extraction lives in this review-specific path (NOT in the generic
    # claude runner, which is shared by implement/research). Fail-closed.
    if fm.get("kind") == "review" and result.status == "done":
        result.verdict, result.verdict_reason = parse_verdict(result.antwort)

    fm["status"] = result.status
    result_fm = _build_result_fm(fm, result, task_id, adapter)
    result_body = result.to_markdown(task_id, fm["claimed_by"], fm["claimed_at"])
    result_path = bc.lane_inbox(lane) / f"result-{task_id}.md"
    # F1/F3: exclusive create — never silently overwrite an existing result.
    # If a result already exists for this task_id, another claim won; we bail
    # and still archive our claimed task so it does not get stuck (F4).
    if not bc.write_text_exclusive(result_path, bc.build_document(result_fm, result_body)):
        print(f"[{lane}] Result für {task_id} existiert bereits — anderer Claim gewann.")
        _archive_claimed(claimed_path, fm, body, lane)
        return False

    # Persist the updated (done) task and move it into _processed/ (no delete).
    bc.write_text_atomic(claimed_path, bc.build_document(fm, body))
    _archive_claimed(claimed_path, fm, body, lane)
    print(f"[{lane}] Verarbeitet: {task_id} → inbox/{result_path.name}")
    return True


def _archive_claimed(claimed_path: bc.Path, fm: dict, body: str, lane: str) -> bool:
    """Move a processed (done) claimed task into _processed/. Returns True on
    success. On failure the file stays put but is logged — poll_once() will
    re-attempt archival on the next pass (F4: no silent stuck tasks)."""
    if not claimed_path.exists():
        return True  # already moved
    dest = bc.lane_processed(lane) / claimed_path.name
    try:
        claimed_path.replace(dest)
        return True
    except OSError as exc:
        print(f"[{lane}] Archivieren fehlgeschlagen für {claimed_path.name}: {exc} — Retry nächster Pass.")
        return False


def _quarantine_claimed(claimed_path: bc.Path, lane: str) -> bool:
    """Move a malformed/hostile stranded claim into _errors/. The destination
    name is derived from the (glob-guaranteed safe) source filename, never from
    the untrusted frontmatter task_id. Never raises."""
    if not claimed_path.exists():
        return True
    bc.lane_errors(lane).mkdir(parents=True, exist_ok=True)
    dest = bc.lane_errors(lane) / claimed_path.name
    try:
        claimed_path.replace(dest)
        return True
    except OSError as exc:
        print(f"[{lane}] Quarantäne fehlgeschlagen für {claimed_path.name}: {exc} — Retry nächster Pass.")
        return False


def _requeue_claimed(claimed_path: bc.Path, fm: dict, body: str, task_id: str, lane: str) -> bool:
    """P0 recovery: a claim that never produced a result is put back as an open
    task so it is not lost. Resets status to open, clears the claim stamps, and
    renames back to task-<id>.md. Uses an exclusive write so we never clobber a
    fresh open task that may already carry this id. Returns True on requeue."""
    if not claimed_path.exists():
        return False
    target = bc.lane_outbox(lane) / f"task-{task_id}.md"
    if target.exists():
        # An open task with this id already exists -> our stranded claim is a
        # duplicate; drop it into _processed/ rather than losing or doubling it.
        return _archive_claimed(claimed_path, fm, body, lane)
    fm = dict(fm)
    fm["status"] = "open"
    fm["claimed_by"] = ""
    fm["claimed_at"] = ""
    if not bc.write_text_exclusive(target, bc.build_document(fm, body)):
        return False  # lost a race to another writer; leave the claim for next pass
    try:
        claimed_path.unlink()
    except OSError:
        pass  # best-effort; the requeued open task is already in place
    return True


def _extract_section(body: str, header: str) -> str | None:
    """Return the text under a '## Header' until the next '## ' or EOF."""
    lines = body.splitlines()
    out: list[str] = []
    capture = False
    for line in lines:
        if line.strip() == header:
            capture = True
            continue
        if capture and line.startswith("## "):
            break
        if capture:
            out.append(line)
    text = "\n".join(out).strip()
    return text or None


def poll_once() -> int:
    bc.ensure_dirs()
    count = 0
    for lane in bc.receive_lanes():
        count += _poll_lane(lane)
    return count


def _poll_lane(lane: str) -> int:
    count = 0

    # F4 + P0: recover stranded .claimed-* tasks from a prior pass. Two cases:
    #  (a) DONE/ERROR with a result already in inbox/ -> just archive (the move
    #      into _processed/ had failed; F4). Safe, no work lost.
    #  (b) OPEN (or done/error but NO result) -> the poller crashed AFTER the
    #      claim but BEFORE writing the result. Blind-archiving here loses the
    #      task forever (P0). Requeue it instead: rename back to task-<id>.md
    #      with status:open so the next pass re-processes it.
    for stranded in sorted(bc.lane_outbox(lane).glob("task-*.claimed-*.md")):
        if _is_conflict_copy(stranded.name):
            continue
        fm, body = bc.parse_frontmatter(bc.read_text_utf8(stranded))
        task_id = fm.get("task_id", bc._task_id_from_name(stranded.name))
        # Security: the recovery path also feeds task_id into result/branch names.
        # The process_one guard does not cover stranded claims, so validate here
        # too — a corrupt/hostile .claimed-* gets quarantined, never honoured.
        if not bc.is_valid_task_id(task_id):
            if _quarantine_claimed(stranded, lane):
                print(f"[{lane}] Stranded-Claim {stranded.name} ungültige task_id → _errors/.")
            continue
        has_result = (bc.lane_inbox(lane) / f"result-{task_id}.md").exists()
        if fm.get("status") in ("done", "error") and has_result:
            if _archive_claimed(stranded, fm, body, lane):
                print(f"[{lane}] Nachgeholt archiviert: {stranded.name}")
        else:
            if _requeue_claimed(stranded, fm, body, task_id, lane):
                print(f"[{lane}] P0-Recovery: {stranded.name} → requeued (open).")

    # Fresh open tasks. Exclude already-claimed names (the glob above handled them).
    for task_path in sorted(bc.lane_outbox(lane).glob("task-*.md")):
        if ".claimed-" in task_path.name or _is_conflict_copy(task_path.name):
            continue
        try:
            if process_one(task_path, lane):
                count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[{lane}] Task {task_path.name} warf {type(exc).__name__}: {exc} — übersprungen.")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Poll + echo bridge tasks (Laptop B).")
    parser.add_argument("--watch", action="store_true", help="Loop forever.")
    parser.add_argument(
        "--interval", type=int, default=15, help="Poll interval seconds (watch mode)."
    )
    args = parser.parse_args(argv)

    if not bc.acquire_singleton_lock():
        print("[B] Ein Poller läuft bereits (Lock gehalten) — ich beende mich.")
        return 0

    print(f"[B] Bridge-Root: {bc.bridge_root()}")
    print(f"[B] Device: {bc.DEVICE}")

    if not args.watch:
        n = poll_once()
        print(f"[B] Durchlauf fertig — {n} Task(s) verarbeitet.")
        return 0

    print(f"[B] Watch-Modus, alle {args.interval}s. Strg+C zum Beenden.")
    try:
        while True:
            n = poll_once()
            if n:
                print(f"[B] {n} Task(s) verarbeitet.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n[B] Beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
