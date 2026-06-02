"""Stage-1 self-driving A<->B ping-pong loop driver (runs on Laptop A).

A is the conductor: it does its own work step inline (local runner), writes a
task into the A->B lane, waits for B's result (with a per-round timeout), then
takes B's payload into the next round. B stays the unchanged handoff_poll worker.

Loop state/history lives A-side in scripts/state/LOOP-<loop_id>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import bridge_common as bc
import runners  # noqa: F401 -- registers echo + increment
import codex_adapter  # noqa: F401
import claude_adapter  # noqa: F401

STATE_DIR = Path(__file__).resolve().parent / "state"


def append_state(loop_id: str, record: dict) -> None:
    """Append one round record to scripts/state/LOOP-<loop_id>.jsonl (history,
    A-side only). Adds an ISO timestamp. Append-only, never deletes."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = dict(record, ts=bc.now_iso())
    path = STATE_DIR / f"LOOP-{loop_id}.jsonl"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_round_task(loop_id: str, round_no: int, payload: str,
                     adapter: str) -> str:
    """Write an open loop task into THIS endpoint's send lane. Returns task_id."""
    bc.ensure_dirs()
    me = bc.this_endpoint()
    lane = bc.send_lane()
    to = next((ep for ep, cfg in bc.ENDPOINTS.items()
               if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": me, "from": me, "to": to, "purpose": "handoff",
        "status": "open", "task_id": task_id, "kind": "echo",
        "adapter": adapter,
        "loop_id": loop_id, "round": str(round_no), "payload": payload,
        "claimed_by": "", "claimed_at": "",
    }
    body = (f"## Auftrag\n{payload}\n\n"
            "## Akzeptanzkriterien\n- [ ] Result im inbox/ mit demselben task_id\n\n"
            "## Ergebnis\n<wird vom Empfaenger gefuellt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def write_review_task(loop_id: str, round_no: int, auftrag: str,
                      loop_branch: str, loop_commit: str, diff: str = "") -> str:
    """Write an open kind:review task to B (claude reviewer). The reviewer runs
    headless WITHOUT tools, so it cannot check out the branch — we embed the
    build diff in the prompt and have it judge the diff text."""
    bc.ensure_dirs()
    me = bc.this_endpoint()
    lane = bc.send_lane()
    to = next((ep for ep, cfg in bc.ENDPOINTS.items()
               if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": me, "from": me, "to": to, "purpose": "handoff",
        "status": "open", "task_id": task_id, "kind": "review",
        "adapter": "claude",
        "loop_id": loop_id, "round": str(round_no),
        "loop_branch": loop_branch, "loop_commit": loop_commit,
        "payload": f"{loop_branch}@{loop_commit}",
        "claimed_by": "", "claimed_at": "",
    }
    diff_block = diff.strip() or "(kein Diff — codex meldete keine Datei-Aenderung)"
    body = (f"## Auftrag\n{auftrag}\n\n"
            f"Der Bau-Agent (codex) hat auf `{loop_branch}` (Commit `{loop_commit}`) "
            "gearbeitet. Hier ist der vollstaendige Diff gegen die Basis. Du hast "
            "KEINE Tools — beurteile den Diff-Text direkt, hol nichts nach.\n\n"
            f"```diff\n{diff_block}\n```\n\n"
            "Reviewe die Aenderung gegen den Auftrag. Schreibe zuerst eine kurze "
            "Begruendung, und als ALLERLETZTE Zeile NUR den Marker — entweder\n"
            "`VERDICT: accepted`\noder\n`VERDICT: rejected`\n"
            "Die Verdikt-Zeile darf NICHTS ausser dem Marker enthalten (keine "
            "Begruendung in derselben Zeile, kein Gedankenstrich, kein Punkt).\n\n"
            "## Ergebnis\n<wird vom Reviewer gefuellt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def _build_review_round(loop_id, round_no, auftrag, repo, base_branch,
                        build_runner, round_timeout, interval=5, b_tick=None):
    """One build→review round. A builds via build_runner (codex), writes a
    kind:review task to B, waits for B's verdict. Returns an outcome dict.
    `b_tick(task_id)` is a test hook; in production B is a separate poller."""
    loop_branch = f"bridge/{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch,
          "workdir_name": loop_id}
    workroot = STATE_DIR / "work"
    try:
        a_res = build_runner(auftrag=auftrag, fm=fm, workroot=workroot)
    except Exception as exc:  # noqa: BLE001 — a runner must not crash the loop
        return {"status": "error", "abort_reason": f"A-build crash: {exc}",
                "verdict": None, "verdict_reason": None, "commit": None,
                "task_id": ""}
    if a_res.status != "done":
        return {"status": "error",
                "abort_reason": f"A-build error: {a_res.error_text}",
                "verdict": None, "verdict_reason": None, "commit": None,
                "task_id": ""}

    task_id = write_review_task(loop_id, round_no, auftrag,
                                loop_branch, a_res.commit or "",
                                diff=a_res.diff or "")
    if b_tick is not None:
        b_tick(task_id)

    fm_result = wait_for_result(task_id, timeout=round_timeout, interval=interval)
    if fm_result is None:
        return {"status": "timeout", "abort_reason": f"timeout in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "task_id": task_id}
    if fm_result.get("status") == "error":
        return {"status": "error", "abort_reason": f"B error in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "task_id": task_id}
    return {"status": "done", "abort_reason": "",
            "verdict": fm_result.get("verdict"),
            "verdict_reason": fm_result.get("verdict_reason"),
            "commit": a_res.commit, "task_id": task_id}


def _is_conflict_copy(name: str) -> bool:
    # Same heuristic as handoff_poll._is_conflict_copy / handoff_collect.
    return "(" in name and ")" in name


def _next_loop_id() -> str:
    return f"loop-{bc.make_task_id()}"


def run_build_review_loop(auftrag, repo, base_branch, max_rounds,
                          round_timeout, interval=5, build_runner=None,
                          b_tick=None):
    """Asymmetric build↔review loop. A builds (codex) on a stable loop branch,
    B reviews (claude, kind:review → verdict). accepted ends; rejected feeds the
    reviewer's gaps into the next build. Bounded by max_rounds, plus an early
    stagnation abort when the build commit is unchanged or the reviewer's reason
    repeats. `build_runner` defaults to the registered codex runner; tests inject
    a fake. Returns a summary dict."""
    if build_runner is None:
        build_runner = runners.RUNNERS["codex"]
    loop_id = _next_loop_id()
    current_auftrag = auftrag
    rounds_done = 0
    accepted = False
    aborted = False
    abort_reason = ""
    final_commit = ""
    open_task_id = ""
    prev_commit = None
    prev_reason = None

    for round_no in range(max_rounds):
        out = _build_review_round(
            loop_id=loop_id, round_no=round_no, auftrag=current_auftrag,
            repo=repo, base_branch=base_branch, build_runner=build_runner,
            round_timeout=round_timeout, interval=interval, b_tick=b_tick)
        append_state(loop_id, {"round": round_no, "side": "build-review",
                               "verdict": out.get("verdict"),
                               "verdict_reason": out.get("verdict_reason"),
                               "commit": out.get("commit"),
                               "task_id": out.get("task_id"),
                               "status": out["status"]})
        if out["status"] != "done":
            aborted, abort_reason = True, out["abort_reason"]
            open_task_id = out.get("task_id", "")
            break
        rounds_done += 1
        final_commit = out.get("commit") or final_commit
        # Unchanged commit wins over a late accept: the verdict already applied
        # to this exact commit, so nothing new happened this round.
        if prev_commit is not None and out.get("commit") == prev_commit:
            aborted, abort_reason = True, "stagniert (kein neuer Commit)"
            break
        prev_commit = out.get("commit")
        if out["verdict"] == "accepted":
            accepted = True
            break
        # rejected
        reason = out.get("verdict_reason")
        if prev_reason is not None and reason == prev_reason:
            aborted, abort_reason = True, "stagniert (Reviewer wiederholt sich)"
            break
        prev_reason = reason
        current_auftrag = (f"{auftrag}\n\nDer Reviewer hat abgelehnt. Behebe:\n"
                           f"{reason or '(keine Begruendung)'}")
    else:
        aborted, abort_reason = True, "max-rounds erreicht, nicht akzeptiert"

    return {
        "loop_id": loop_id, "rounds_done": rounds_done, "accepted": accepted,
        "final_commit": final_commit, "aborted": aborted,
        "abort_reason": abort_reason, "open_task_id": open_task_id,
        "final_branch": f"bridge/{loop_id}",
    }


def run_loop(seed: str, max_rounds: int, adapter: str, round_timeout: int,
             interval: float = 5, b_tick=None) -> dict:
    """Drive the ping-pong loop. Each round: A works inline on the current
    payload, writes a task to B, waits for B's result (timeout), takes B's
    payload as the next round's input. `b_tick` is an optional callable invoked
    once per round AFTER the task is written (tests use it to run a local B
    poll; in production B is a separate live poller, so b_tick stays None).

    Returns a summary dict. fail-safe: on timeout / B-error / runner crash the
    loop aborts cleanly (no hang) and reports the open task_id + last payload."""
    loop_id = _next_loop_id()
    payload = seed
    rounds_done = 0
    aborted = False
    abort_reason = ""
    open_task_id = ""

    for round_no in range(max_rounds):
        a_payload = ""  # bound even if the A-runner aborts before computing it
        # 1. A works inline on the current payload.
        runner = runners.RUNNERS.get(adapter)
        if runner is None:
            aborted, abort_reason = True, f"unbekannter adapter {adapter!r}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": payload, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        try:
            a_res = runner(auftrag=payload, fm={"payload": payload},
                           workroot=None)
        except Exception as exc:  # noqa: BLE001 -- a runner must not crash the loop
            aborted, abort_reason = True, f"A-runner crash: {exc}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": payload, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        if a_res.status != "done":
            aborted, abort_reason = True, f"A-runner error: {a_res.error_text}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": payload, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        a_payload = a_res.antwort.strip()

        # 2. Write task to B with A's freshly computed payload.
        task_id = write_round_task(loop_id, round_no, a_payload, adapter)
        open_task_id = task_id

        # 3. (tests only) let a local B worker process the task.
        if b_tick is not None:
            b_tick()

        # 4. Wait for B's result (per-round timeout -> clean abort).
        fm = wait_for_result(task_id, timeout=round_timeout, interval=interval)
        if fm is None:
            aborted, abort_reason = True, f"timeout in round {round_no}"
            append_state(loop_id, {"round": round_no, "side": "B",
                                   "payload_in": a_payload, "payload_out": "",
                                   "task_id": task_id, "status": "timeout"})
            break
        if fm.get("status") == "error":
            aborted, abort_reason = True, f"B error in round {round_no}"
            append_state(loop_id, {"round": round_no, "side": "B",
                                   "payload_in": a_payload, "payload_out": "",
                                   "task_id": task_id, "status": "error"})
            break

        b_payload = fm.get("payload", "")
        append_state(loop_id, {"round": round_no, "side": "B",
                               "payload_in": a_payload, "payload_out": b_payload,
                               "task_id": task_id, "status": "done"})
        payload = b_payload
        rounds_done += 1
        open_task_id = ""

    return {
        "loop_id": loop_id, "rounds_done": rounds_done,
        "final_payload": payload, "aborted": aborted,
        "abort_reason": abort_reason, "open_task_id": open_task_id,
    }


def wait_for_result(task_id: str, timeout: int, interval: float = 5):
    """Poll the send lane's inbox for result-<task_id>.md until it appears or
    `timeout` seconds elapse. Returns the result frontmatter dict, or None on
    timeout. Checks at least once (so timeout=0 still inspects). Drive conflict
    copies ('(1)') are ignored. A half-written file (frontmatter parsed but no
    task_id yet — a real risk on slow Drive sync) is treated as a miss and
    polling continues, never returned as an empty hit. On a real hit the file is
    archived into _processed/ so it is not re-read next round (best-effort).

    B writes results into the inbox of the lane it polled (A-to-B/inbox/), which
    is the same lane A sent the task on. So we poll bc.send_lane()'s inbox, not
    bc.receive_lanes()[0] (that lane is for tasks B proactively sends to A)."""
    lane = bc.send_lane()
    target_name = f"result-{task_id}.md"
    deadline = time.monotonic() + timeout
    while True:
        path = bc.lane_inbox(lane) / target_name
        if path.exists() and not _is_conflict_copy(path.name):
            fm, _ = bc.parse_frontmatter(bc.read_text_utf8(path))
            if fm.get("task_id"):  # complete file — a real hit
                try:
                    (bc.lane_processed(lane) / target_name).unlink(missing_ok=True)
                    path.replace(bc.lane_processed(lane) / target_name)
                except OSError:
                    pass  # best-effort archive; we already have the fm
                return fm
            # else: half-written, keep waiting
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-driving A<->B ping-pong loop (runs on Laptop A).")
    parser.add_argument("--seed", default="0", help="Start payload (round 0 input).")
    parser.add_argument("--max-rounds", type=int, required=True,
                        help="Stop after exactly N rounds.")
    parser.add_argument("--adapter", default="increment",
                        choices=["echo", "increment", "codex", "claude"],
                        help="Runner both sides use per round.")
    parser.add_argument("--round-timeout", type=int, default=300,
                        help="Max seconds to wait for B's result per round.")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Poll interval seconds while waiting for a result.")
    parser.add_argument("--mode", default="ping-pong",
                        choices=["ping-pong", "build-review"],
                        help="ping-pong (Stage 1) or build-review (Stage 2b).")
    parser.add_argument("--repo", default="",
                        help="Repo URL/path to build in (build-review mode).")
    parser.add_argument("--base-branch", default="main",
                        help="Base branch to start the loop branch from.")
    args = parser.parse_args(argv)

    # Singleton: one loop driver per machine (reuses the poller lock pattern,
    # local lock file, never the Drive root). Uses a loop-specific lock name.
    lock = bc.default_lock_path().with_name("dual-bridge-loop.lock")
    if not bc.acquire_singleton_lock(lock):
        print("[A] Ein Loop-Treiber laeuft bereits -- ich beende mich.")
        return 0

    if args.mode == "build-review":
        if not args.repo:
            print("[A] --mode build-review braucht --repo.")
            return 2
        print(f"[A] Build-Review-Loop: repo={args.repo} "
              f"base={args.base_branch} max_rounds={args.max_rounds}")
        try:
            summary = run_build_review_loop(
                auftrag=args.seed, repo=args.repo, base_branch=args.base_branch,
                max_rounds=args.max_rounds, round_timeout=args.round_timeout,
                interval=args.interval, build_runner=None, b_tick=None)
        except KeyboardInterrupt:
            print("\n[A] Strg+C -- Loop abgebrochen.")
            return 1
        print("=" * 60)
        print(f"[A] Build-Review-Loop {summary['loop_id']} fertig.")
        print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
        print(f"    Akzeptiert: {summary['accepted']}")
        print(f"    Branch: {summary['final_branch']} @ {summary['final_commit']}")
        if summary["aborted"]:
            print(f"    ABGEBROCHEN: {summary['abort_reason']}")
            if summary["open_task_id"]:
                print(f"    Offener Task: {summary['open_task_id']}")
        print(f"    History: {STATE_DIR / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
        print("=" * 60)
        return 0 if summary["accepted"] else 1

    print(f"[A] Bridge-Root: {bc.bridge_root()}")
    print(f"[A] Loop: seed={args.seed} max_rounds={args.max_rounds} "
          f"adapter={args.adapter} round_timeout={args.round_timeout}s")
    try:
        summary = run_loop(seed=args.seed, max_rounds=args.max_rounds,
                           adapter=args.adapter,
                           round_timeout=args.round_timeout,
                           interval=args.interval, b_tick=None)
    except KeyboardInterrupt:
        print("\n[A] Strg+C -- Loop abgebrochen.")
        return 1

    print("=" * 60)
    print(f"[A] Loop {summary['loop_id']} fertig.")
    print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
    print(f"    Final-Payload: {summary['final_payload']}")
    if summary["aborted"]:
        print(f"    ABGEBROCHEN: {summary['abort_reason']}")
        if summary["open_task_id"]:
            print(f"    Offener Task (liegt in der Lane): {summary['open_task_id']}")
    print(f"    History: {STATE_DIR / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
    print("=" * 60)
    return 1 if summary["aborted"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
