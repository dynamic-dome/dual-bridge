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
import codex_adapter as ca

# Stage 1 codex config (overridable via env on Laptop B).
CODEX_BIN = os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None
CODEX_WORKROOT = bc.Path(
    os.environ.get("DUAL_BRIDGE_WORKROOT")
    or (bc.Path.home() / "dual-bridge-work")
)
CODEX_TIMEOUT = int(os.environ.get("DUAL_BRIDGE_CODEX_TIMEOUT", "600"))
LLM_KINDS = {"implement", "research", "review", "test"}


def _is_conflict_copy(name: str) -> bool:
    """Google-Drive conflict copies look like 'task-... (1).md'. Skip them."""
    return "(" in name and ")" in name


def process_one(task_path: bc.Path) -> bool:
    """Claim + echo a single task file. Returns True if a result was written."""
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(task_path))
    if fm.get("status") != "open":
        return False  # already claimed/done by someone else

    task_id = fm.get("task_id", task_path.stem.replace("task-", ""))
    # Security: the task_id reaches a result filename and a git branch name.
    # Reject anything that is not a well-formed make_task_id() to close
    # path-traversal / branch-injection via a hostile/corrupt task file.
    if not bc.is_valid_task_id(task_id):
        print(f"[B] Task {task_path.name} hat ungültige task_id {task_id!r} — übersprungen.")
        return False
    claimed_path = bc.claim_task(task_path, bc.DEVICE)
    if claimed_path is None:
        print(f"[B] Konnte {task_path.name} nicht claimen (Race/Lock) — übersprungen.")
        return False

    # Re-read from the claimed path to confirm we hold the canonical content.
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(claimed_path))
    fm["claimed_by"] = f"laptop-b-worker@{bc.DEVICE}"
    fm["claimed_at"] = bc.now_iso()

    # --- Stage 0 echo OR Stage 1 codex, by kind ----------------------------
    kind = fm.get("kind", "echo")
    extra_fm: dict[str, str] = {}
    if kind in LLM_KINDS:
        repo = fm.get("repo", "")
        base_branch = fm.get("base_branch", "main")
        if not repo:
            result_status = "error"
            result_body = (
                "## Fehler\n"
                f"Task {task_id} ist kind:{kind}, hat aber kein `repo:`-Feld. "
                "Laptop A muss --repo angeben.\n"
            )
        else:
            print(f"[B] codex exec für task {task_id} (kind={kind}, repo={repo}) ...")
            cr = ca.run_codex_task(
                auftrag=_extract_section(body, "## Auftrag") or body.strip(),
                repo=repo, base_branch=base_branch, task_id=task_id,
                workroot=CODEX_WORKROOT, codex_bin=CODEX_BIN, timeout=CODEX_TIMEOUT,
            )
            result_status = cr.status
            result_body = _build_codex_result_body(task_id, fm, cr)
            if cr.branch:
                extra_fm["branch"] = cr.branch
            if cr.commit:
                extra_fm["commit"] = cr.commit
    else:
        # Stage 0 echo (unchanged behaviour).
        result_status = "done"
        auftrag = _extract_section(body, "## Auftrag") or body.strip()
        result_body = (
            "## Quelle\n"
            f"task_id {task_id}, geclaimt von {fm['claimed_by']} um {fm['claimed_at']}\n\n"
            "## Echo (Stage 0 — kein LLM)\n"
            f"{auftrag}\n\n"
            "## Hinweis\n"
            "Dies ist die elementare Stage-0-Antwort: Laptop B hat den Task gelesen "
            "und den Auftragstext zurückgespiegelt. In Stage 1 ersetzt ein echter "
            "Codex-/Claude-Aufruf dieses Echo.\n"
        )

    fm["status"] = result_status
    result_fm = {
        "created": bc.now_iso(),
        "agent": fm["claimed_by"],
        "target_agent": fm.get("agent", "laptop-a-claude"),
        "purpose": "handoff",
        "status": result_status,
        "task_id": task_id,
        "kind": fm.get("kind", "echo"),
        "replies_to": f"task-{task_id}.md",
        **extra_fm,
    }
    result_doc = bc.build_document(result_fm, result_body)
    result_path = bc.inbox_dir() / f"result-{task_id}.md"
    # F1/F3: exclusive create — never silently overwrite an existing result.
    # If a result already exists for this task_id, another claim won; we bail
    # and still archive our claimed task so it does not get stuck (F4).
    if not bc.write_text_exclusive(result_path, result_doc):
        print(f"[B] Result für {task_id} existiert bereits — anderer Claim gewann. Archiviere Task.")
        _archive_claimed(claimed_path, fm, body)
        return False

    # Persist the updated (done) task and move it into _processed/ (no delete).
    bc.write_text_atomic(claimed_path, bc.build_document(fm, body))
    _archive_claimed(claimed_path, fm, body)

    print(f"[B] Verarbeitet: task_id {task_id} → inbox/{result_path.name}")
    return True


def _archive_claimed(claimed_path: bc.Path, fm: dict, body: str) -> bool:
    """Move a processed (done) claimed task into _processed/. Returns True on
    success. On failure the file stays put but is logged — poll_once() will
    re-attempt archival on the next pass (F4: no silent stuck tasks)."""
    if not claimed_path.exists():
        return True  # already moved
    dest = bc.processed_dir() / claimed_path.name
    try:
        claimed_path.replace(dest)
        return True
    except OSError as exc:
        print(f"[B] Archivieren fehlgeschlagen für {claimed_path.name}: {exc} — Retry nächster Pass.")
        return False


def _quarantine_claimed(claimed_path: bc.Path) -> bool:
    """Move a malformed/hostile stranded claim into _errors/. The destination
    name is derived from the (glob-guaranteed safe) source filename, never from
    the untrusted frontmatter task_id. Never raises."""
    if not claimed_path.exists():
        return True
    bc.errors_dir().mkdir(parents=True, exist_ok=True)
    dest = bc.errors_dir() / claimed_path.name
    try:
        claimed_path.replace(dest)
        return True
    except OSError as exc:
        print(f"[B] Quarantäne fehlgeschlagen für {claimed_path.name}: {exc} — Retry nächster Pass.")
        return False


def _requeue_claimed(claimed_path: bc.Path, fm: dict, body: str, task_id: str) -> bool:
    """P0 recovery: a claim that never produced a result is put back as an open
    task so it is not lost. Resets status to open, clears the claim stamps, and
    renames back to task-<id>.md. Uses an exclusive write so we never clobber a
    fresh open task that may already carry this id. Returns True on requeue."""
    if not claimed_path.exists():
        return False
    target = bc.outbox_dir() / f"task-{task_id}.md"
    if target.exists():
        # An open task with this id already exists -> our stranded claim is a
        # duplicate; drop it into _processed/ rather than losing or doubling it.
        return _archive_claimed(claimed_path, fm, body)
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


def _build_codex_result_body(task_id: str, fm: dict, cr: "ca.CodexResult") -> str:
    """Render a result body from a CodexResult. On done with a branch, include
    the git-pull hint; on error, surface the error + stderr prominently."""
    lines = [
        "## Quelle",
        f"task_id {task_id}, geclaimt von {fm.get('claimed_by','?')} um {fm.get('claimed_at','?')}",
        "",
    ]
    if cr.status == "done":
        lines += ["## Codex-Antwort", cr.antwort, ""]
        if cr.branch and cr.commit:
            lines += [
                "## Artefakt (Git)",
                f"Branch `{cr.branch}` auf dem Remote, Commit `{cr.commit}`.",
                f"Geänderte Dateien: {', '.join(cr.changed_files) or '—'}",
                "",
                "## So holst du es (auf A)",
                "```",
                f"git fetch && git checkout {cr.branch}",
                "```",
                "",
            ]
        elif cr.note:
            lines += ["## Hinweis", cr.note, ""]
    else:
        lines += [
            "## FEHLER",
            cr.error_text or "unbekannter Fehler",
            "",
        ]
        if cr.antwort:
            lines += ["## Codex-Antwort (trotz Fehler erhalten)", cr.antwort, ""]
        if cr.stderr_excerpt:
            lines += ["## stderr (Auszug)", "```", cr.stderr_excerpt, "```", ""]
    return "\n".join(lines)


def poll_once() -> int:
    bc.ensure_dirs()
    count = 0

    # F4 + P0: recover stranded .claimed-* tasks from a prior pass. Two cases:
    #  (a) DONE/ERROR with a result already in inbox/ -> just archive (the move
    #      into _processed/ had failed; F4). Safe, no work lost.
    #  (b) OPEN (or done/error but NO result) -> the poller crashed AFTER the
    #      claim but BEFORE writing the result. Blind-archiving here loses the
    #      task forever (P0). Requeue it instead: rename back to task-<id>.md
    #      with status:open so the next pass re-processes it.
    for stranded in sorted(bc.outbox_dir().glob("task-*.claimed-*.md")):
        if _is_conflict_copy(stranded.name):
            continue
        fm, body = bc.parse_frontmatter(bc.read_text_utf8(stranded))
        task_id = fm.get("task_id", bc._task_id_from_name(stranded.name))
        # Security: the recovery path also feeds task_id into result/branch names.
        # The process_one guard does not cover stranded claims, so validate here
        # too — a corrupt/hostile .claimed-* gets quarantined, never honoured.
        if not bc.is_valid_task_id(task_id):
            if _quarantine_claimed(stranded):
                print(f"[B] Stranded-Claim {stranded.name} mit ungültiger task_id {task_id!r} → _errors/.")
            continue
        has_result = (bc.inbox_dir() / f"result-{task_id}.md").exists()
        if fm.get("status") in ("done", "error") and has_result:
            if _archive_claimed(stranded, fm, body):
                print(f"[B] Nachgeholt archiviert: {stranded.name}")
        else:
            if _requeue_claimed(stranded, fm, body, task_id):
                print(f"[B] P0-Recovery: {stranded.name} ohne Result → requeued (status:open).")

    # Fresh open tasks. Exclude already-claimed names (the glob above handled them).
    for task_path in sorted(bc.outbox_dir().glob("task-*.md")):
        if ".claimed-" in task_path.name:
            continue
        if _is_conflict_copy(task_path.name):
            print(f"[B] Drive-Conflict-Copy ignoriert: {task_path.name}")
            continue
        try:
            if process_one(task_path):
                count += 1
        except Exception as exc:  # noqa: BLE001 — one bad task must not kill the poller
            print(f"[B] Task {task_path.name} warf {type(exc).__name__}: {exc} — übersprungen.")
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
