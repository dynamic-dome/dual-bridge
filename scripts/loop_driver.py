"""Stage-1 self-driving A<->B ping-pong loop driver (runs on Laptop A).

A is the conductor: it does its own work step inline (local runner), writes a
task into the A->B lane, waits for B's result (with a per-round timeout), then
takes B's payload into the next round. B stays the unchanged handoff_poll worker.

Loop state/history lives A-side in scripts/state/LOOP-<loop_id>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import bridge_common as bc
import runners  # noqa: F401 -- registers echo + increment
import codex_adapter  # noqa: F401
import claude_adapter  # noqa: F401

STATE_DIR = Path(__file__).resolve().parent / "state"


def _reason_carries_signal(reason: str | None) -> bool:
    """True only if a reject reason holds a real, differentiating signal.

    Repeated-reason stagnation must NOT fire on no-signal reasons. Two cases:
      - empty/whitespace: parse_verdict returns ('rejected', '') for every plain
        reject, so '' == '' would spuriously stagnate after two real rounds.
      - bare Markdown heading: parse_frontmatter keeps only the FIRST line of a
        multi-line YAML payload, so a reviewer answer that opens with a
        '## Begründung' heading collapses to that heading EVERY round (live
        seed-02 false stagnation, 2026-06-03). A line that is only a heading
        (starts with '#', no prose after the marker) carries no comparison value.
    The same-commit guard already catches genuine no-progress, so dropping these
    only removes a false positive, never a real stall."""
    if not reason or not reason.strip():
        return False
    stripped = reason.strip()
    # A pure ATX heading ('# ', '## ' … then a label) on a single line is
    # boilerplate, not a differentiating reason. Require the '#'-run to be
    # followed by a space so a real reason like '#123 test still failing' (no
    # space after '#') still counts as signal (Codex review minor 2026-06-03).
    if "\n" not in stripped:
        marker = stripped[:len(stripped) - len(stripped.lstrip("#"))]
        if marker and stripped[len(marker):len(marker) + 1] == " ":
            return False
    return True


def _reason_from_body(body: str | None) -> str:
    """Pull the reviewer's real reasoning out of a result document body.

    parse_frontmatter keeps only the FIRST line of a multi-line YAML payload, so
    the frontmatter 'payload' collapses to a bare '## Begründung' heading and the
    real reason is lost there (known-MINOR, 2026-06-03). The full reasoning still
    lives in the document body, under '## Antwort' and/or a '## Begründung'
    heading. Return the prose under those headings (the VERDICT marker line and
    surrounding blank lines stripped), or '' if nothing usable is found."""
    if not body:
        return ""
    lines = body.splitlines()
    # Find the start of the reasoning: prefer a '## Begründung' heading, else the
    # '## Antwort' section, else the whole body.
    start = 0
    for i, ln in enumerate(lines):
        s = ln.strip().lower()
        if s.startswith("##") and "begründung" in s:
            start = i + 1
            break
        if s.startswith("##") and "antwort" in s:
            start = i + 1  # keep scanning — a later Begründung wins
    kept = []
    for ln in lines[start:]:
        s = ln.strip()
        if s.lower().startswith("verdict:") or s.lower().startswith("verdict_reason:"):
            continue  # machine markers, not prose
        if s.startswith("##"):
            low = s.lower()
            if "begründung" in low or "antwort" in low:
                continue  # a repeated reason heading — skip it, keep its content
            break  # a FOREIGN section (## Verdikt / ## Artefakt …) ends the reason
        kept.append(ln)
    return "\n".join(kept).strip()


def parse_seed(seed_text: str) -> tuple[str, list[str]]:
    """Split a structured goal-loop seed into (goal, done_criteria).

    Format (Markdown):
        ## Ziel
        <prose goal>

        ## Done-Kriterien
        - [ ] criterion 1
        - [ ] criterion 2

    The goal is the prose under `## Ziel`. Criteria are the checklist items
    under `## Done-Kriterien` (the `- [ ]`/`- [x]` prefix is stripped).
    Raises ValueError if either block is missing or the criteria list is empty.
    """
    goal_lines: list[str] = []
    criteria: list[str] = []
    section = None
    for raw in seed_text.splitlines():
        line = raw.rstrip()
        low = line.strip().lower()
        if low.startswith("## ziel"):
            section = "goal"
            continue
        if low.startswith("## done-kriterien"):
            section = "criteria"
            continue
        if section == "goal" and line.strip():
            goal_lines.append(line.strip())
        elif section == "criteria":
            stripped = line.strip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                # strip a leading checkbox: [ ] / [x] / [X]
                if item[:3] in ("[ ]", "[x]", "[X]"):
                    item = item[3:].strip()
                if item:
                    criteria.append(item)
    goal = " ".join(goal_lines).strip()
    if not goal:
        raise ValueError("seed has no '## Ziel' block")
    if not criteria:
        raise ValueError("seed has no done-criteria under '## Done-Kriterien'")
    return goal, criteria


# Deny-first patterns — mirrored from orchestrated-bridge's secret-sweep
# (gate_secret_sweep.py) + a few destructive shell/SQL patterns. Mirrored, not
# imported, because the gate lives in a separate repo; a later task adds a drift
# test that fails if the mirror falls behind. A hit escalates (trigger:
# dangerous_action) — never a cross-device gate roundtrip (latency dead-end).
DANGEROUS_PATTERNS = [
    r"push\s+.*--force",
    r"push\s+--force",
    r"\bforce-push\b",
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\brm\s+-rf\b",
    r"sk-ant-[A-Za-z0-9_-]+",
    r"\bapi[_-]?key\b\s*[=:]",
]
_DANGEROUS_RE = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]

_DELETE_FROM_PAT = r"\bDELETE\s+FROM\b"
# A row-targeted CRUD delete: `DELETE FROM <tbl> WHERE ... <placeholder>` where
# the predicate is bound (`?`, `:name`, `%s`, `%(name)s`). This is the OPPOSITE
# of the destructive mass-delete the guard exists to stop — a bound placeholder
# means a specific row, not a table wipe. False-Positive 2026-06-07: the
# reminders-v2 goal-loop escalated in round 0 on a legit `delete(id)` method.
_CRUD_DELETE_RE = re.compile(
    r"\bDELETE\s+FROM\b.*\bWHERE\b.*(?:\?|:\w+|%\(\w+\)s|%s)",
    re.IGNORECASE,
)


def _delete_from_is_safe(text: str) -> bool:
    """True only if EVERY `DELETE FROM` occurrence in `text` is the safe,
    parametrised single-row CRUD shape. One bare or unparametrised DELETE FROM
    (no WHERE, or a WHERE without a bound placeholder) makes the whole text
    unsafe — we must not let a safe CRUD line in a diff mask a mass-delete
    elsewhere in the same diff."""
    delete_re = re.compile(_DELETE_FROM_PAT, re.IGNORECASE)
    saw_delete = False
    for line in text.splitlines() or [text]:
        if delete_re.search(line):
            saw_delete = True
            if not _CRUD_DELETE_RE.search(line):
                return False
    return saw_delete


def scan_dangerous(text: str) -> str | None:
    """Return the first dangerous pattern found in `text`, or None if clean.
    Deny-first: used by the goal-loop to escalate (NOT block) risky build
    actions/diffs locally, without any cross-device gate roundtrip."""
    if not text:
        return None
    for pat, rx in zip(DANGEROUS_PATTERNS, _DANGEROUS_RE):
        if rx.search(text):
            # Allow legitimate parametrised CRUD deletes through the otherwise
            # bare DELETE-FROM guard (the pattern stays in DANGEROUS_PATTERNS for
            # the drift mirror; the exception lives here, not in the list).
            if pat == _DELETE_FROM_PAT and _delete_from_is_safe(text):
                continue
            return pat
    return None


def append_state(loop_id: str, record: dict) -> None:
    """Append one round record to scripts/state/LOOP-<loop_id>.jsonl (history,
    A-side only). Adds an ISO timestamp. Append-only, never deletes."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = dict(record, ts=bc.now_iso())
    path = STATE_DIR / f"LOOP-{loop_id}.jsonl"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_round_task(loop_id: str, round_no: int, payload: str,
                     adapter: str, repo: str = "", base_branch: str = "main",
                     loop_branch: str = "") -> str:
    """Write an open loop task into THIS endpoint's send lane. Returns task_id.

    For git-building adapters (codex/claude) repo/base_branch/loop_branch are
    embedded so B's runner builds on the SAME loop branch as A (continuity across
    the handoff). For text adapters (echo) they are empty and ignored; B's
    _codex_runner is never reached because the adapter is echo."""
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
        "repo": repo, "base_branch": base_branch,
        "branch": loop_branch or f"bridge/{loop_id}",
        "workdir_name": loop_id,
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


def write_goal_review_task(loop_id: str, round_no: int, goal: str,
                           done_criteria: list[str], loop_branch: str,
                           loop_commit: str, diff: str = "") -> str:
    """Write a goal-loop kind:review task to B. The reviewer judges the diff
    against the explicit done-criteria and answers with one of THREE markers:
    accepted (all criteria met), escalate (needs a human decision), or rejected
    (gaps remain). Tool-less reviewer → diff embedded in the prompt."""
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
    crit_block = "\n".join(f"- [ ] {c}" for c in done_criteria)
    body = (
        f"## Ziel\n{goal}\n\n"
        f"## Done-Kriterien\n{crit_block}\n\n"
        f"Der Bau-Agent (codex) hat auf `{loop_branch}` (Commit `{loop_commit}`) "
        "gearbeitet. Hier ist der vollstaendige Diff gegen die Basis. Du hast "
        "KEINE Tools — beurteile den Diff-Text direkt, hol nichts nach.\n\n"
        f"```diff\n{diff_block}\n```\n\n"
        "Pruefe den Diff GEGEN die Done-Kriterien. Schreibe zuerst eine kurze "
        "Begruendung (welche Kriterien erfuellt sind, welche nicht), und als "
        "ALLERLETZTE Zeile NUR einen der drei Marker:\n"
        "`VERDICT: accepted`   (alle Done-Kriterien erfuellt)\n"
        "`VERDICT: rejected`   (Kriterien noch offen, Bau soll nachbessern)\n"
        "`VERDICT: escalate`   (eine menschliche Entscheidung ist noetig — "
        "mehrdeutiges Kriterium, Architektur-/Risiko-Frage)\n"
        "Die Verdikt-Zeile darf NICHTS ausser dem Marker enthalten.\n\n"
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


def _goal_build_review_round(loop_id, round_no, goal, done_criteria, auftrag,
                             repo, base_branch, build_runner, round_timeout,
                             interval=5, b_tick=None):
    """One goal-loop build→review round. Like _build_review_round but the review
    task lists the done-criteria (write_goal_review_task)."""
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
                "diff": "", "task_id": ""}
    if a_res.status != "done":
        return {"status": "error",
                "abort_reason": f"A-build error: {a_res.error_text}",
                "verdict": None, "verdict_reason": None, "commit": None,
                "diff": "", "task_id": ""}
    danger = scan_dangerous((a_res.diff or "") + "\n" + auftrag)
    if danger is not None:
        return {"status": "dangerous", "abort_reason": f"dangerous: {danger}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": "",
                "danger": danger}
    task_id = write_goal_review_task(loop_id, round_no, goal, done_criteria,
                                     loop_branch, a_res.commit or "",
                                     diff=a_res.diff or "")
    if b_tick is not None:
        b_tick(task_id)
    fm_result = wait_for_result(task_id, timeout=round_timeout, interval=interval)
    if fm_result is None:
        return {"status": "timeout", "abort_reason": f"timeout in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}
    if fm_result.get("status") == "error":
        return {"status": "error", "abort_reason": f"B error in round {round_no}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}
    # parse_verdict yields an empty reason for accepted/escalate/bare-rejected.
    # The reviewer's full analysis lives in the document BODY; the frontmatter
    # `payload` is truncated to its first line ('## Begründung') by
    # parse_frontmatter, so prefer the body-extracted reason when neither the
    # explicit verdict_reason nor a body reason... fall back to payload last so
    # the escalation file carries real reasoning, not a bare heading (known-MINOR
    # 2026-06-03).
    reason = fm_result.get("verdict_reason")
    if not _reason_carries_signal(reason):
        body_reason = _reason_from_body(fm_result.get("_body"))
        reason = body_reason or fm_result.get("payload") or reason or ""
    return {"status": "done", "abort_reason": "",
            "verdict": fm_result.get("verdict"),
            "verdict_reason": reason,
            "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}


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
        # rejected — same no-signal guard as the goal-loop (empty reason / bare
        # Markdown heading must not be read as a repeated differentiating reason).
        reason = out.get("verdict_reason")
        if (_reason_carries_signal(reason) and _reason_carries_signal(prev_reason)
                and reason == prev_reason):
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


def _escalation_path(loop_id: str):
    return STATE_DIR / f"ESCALATION-{loop_id}.md"


def write_escalation(loop_id: str, trigger: str, round_no: int, branch: str,
                     commit: str, goal: str,
                     criteria_status: list[tuple[str, bool]], reason: str,
                     question: str, progress: str):
    """Write ESCALATION-<loop_id>.md (the durable escalation artefact). Returns
    the path. `criteria_status` is a list of (criterion, met) pairs. NOTE: the
    loop does not yet machine-capture per-criterion status from the reviewer, so
    we render the criteria as a plain list and do NOT emit '[x]'/'[ ]' checkboxes
    that would assert a met/unmet state the loop never measured (would mislead
    the resuming owner). The `met` flags are accepted for forward-compat with a
    future per-criterion tracker but are only surfaced when a criterion is
    actually marked met."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fm = {
        "loop_id": loop_id, "trigger": trigger, "round": str(round_no),
        "branch": branch, "commit": commit, "exit_reason": "escalation",
        "created": bc.now_iso(),
    }
    any_met = any(met for _name, met in criteria_status)
    if any_met:
        crit_lines = "\n".join(
            f"- [{'x' if met else ' '}] {name}" for name, met in criteria_status)
    else:
        # No machine-measured progress — list honestly, no checkbox theatre.
        crit_lines = "\n".join(f"- {name}" for name, _met in criteria_status)
    body = (
        f"## Ziel (aus dem Seed)\n{goal}\n\n"
        f"## Done-Kriterien (Stand vom Reviewer nicht maschinell erfasst)\n"
        f"{crit_lines}\n\n"
        f"## Eskalations-Grund\n{reason}\n\n"
        f"## Offene Frage an den Owner\n{question}\n\n"
        f"## Zwischenstand\n{progress}\n")
    path = _escalation_path(loop_id)
    bc.write_text_utf8(path, bc.build_document(fm, body))
    return path


def read_escalation(loop_id: str) -> dict | None:
    """Read the frontmatter of ESCALATION-<loop_id>.md (for resume validation).
    Returns the frontmatter dict, or None if the file does not exist."""
    path = _escalation_path(loop_id)
    if not path.exists():
        return None
    fm, _body = bc.parse_frontmatter(path.read_text(encoding="utf-8"))
    return fm


def _escalate(loop_id, trigger, round_no, branch, commit, goal, done_criteria,
              prev_commit, reason, question, met_criteria=None):
    """Write the escalation file for any of the four triggers."""
    met = set(met_criteria or [])
    criteria_status = [(c, c in met) for c in done_criteria]
    progress = (f"Letzter Commit: {commit or '(keiner)'} auf {branch}. "
                f"Runde {round_no}.")
    write_escalation(loop_id=loop_id, trigger=trigger, round_no=round_no,
                     branch=branch, commit=commit or "", goal=goal,
                     criteria_status=criteria_status, reason=reason,
                     question=question, progress=progress)


def run_goal_loop(goal, done_criteria, repo, base_branch, max_rounds,
                  round_timeout, interval=5, build_runner=None, b_tick=None,
                  loop_id=None):
    """Free work-loop toward an open goal (Stage 3). A builds (codex) on a
    stable loop branch toward `goal`; B reviews the diff against `done_criteria`
    (kind:review → accepted | rejected | escalate). accepted ends successfully.
    rejected feeds the reviewer's gaps into the next build. Four triggers
    escalate (write ESCALATION + stop, nonzero): reviewer escalate, stagnation,
    max-rounds, dangerous-action. `loop_id` lets resume reuse the same branch.
    Returns a summary dict."""
    if build_runner is None:
        build_runner = runners.RUNNERS["codex"]
    if loop_id is None:
        loop_id = _next_loop_id()
    loop_branch = f"bridge/{loop_id}"
    base_auftrag = (f"Ziel: {goal}\n\nDone-Kriterien:\n"
                    + "\n".join(f"- {c}" for c in done_criteria))
    current_auftrag = base_auftrag
    rounds_done = 0
    accepted = False
    escalated = False
    escalation_trigger = ""
    final_commit = ""
    prev_commit = None
    prev_reason = None

    def _summary():
        return {
            "loop_id": loop_id, "rounds_done": rounds_done, "accepted": accepted,
            "escalated": escalated, "escalation_trigger": escalation_trigger,
            "final_commit": final_commit, "final_branch": loop_branch,
        }

    for round_no in range(max_rounds):
        out = _goal_build_review_round(
            loop_id=loop_id, round_no=round_no, goal=goal,
            done_criteria=done_criteria, auftrag=current_auftrag, repo=repo,
            base_branch=base_branch, build_runner=build_runner,
            round_timeout=round_timeout, interval=interval, b_tick=b_tick)
        append_state(loop_id, {"round": round_no, "side": "goal-loop",
                               "verdict": out.get("verdict"),
                               "verdict_reason": out.get("verdict_reason"),
                               "commit": out.get("commit"),
                               "status": out["status"]})
        if out["status"] == "dangerous":
            escalated = True
            escalation_trigger = "dangerous_action"
            _escalate(loop_id, "dangerous_action", round_no, loop_branch,
                      out.get("commit") or final_commit, goal, done_criteria,
                      prev_commit,
                      reason=f"Gefaehrliches Muster im Diff/Auftrag erkannt: "
                             f"{out.get('danger')!r} (deny-first, lokal).",
                      question="Ist diese Aktion gewollt? Falls ja: bewusst "
                               "manuell ausfuehren. Sonst Seed schaerfen + --resume.")
            break
        if out["status"] != "done":
            escalated = True
            escalation_trigger = "stagnation"
            _escalate(loop_id, "stagnation", round_no, loop_branch,
                      out.get("commit") or final_commit, goal, done_criteria,
                      prev_commit, reason=out.get("abort_reason", "round failed"),
                      question="Der Loop konnte nicht fortfahren. Bitte pruefen.")
            break
        rounds_done += 1
        final_commit = out.get("commit") or final_commit

        if out["verdict"] == "accepted":
            accepted = True
            break
        if out["verdict"] == "escalate":
            escalated = True
            escalation_trigger = "reviewer_requested"
            _escalate(loop_id, "reviewer_requested", round_no, loop_branch,
                      out.get("commit") or final_commit, goal, done_criteria,
                      prev_commit,
                      reason=f"Reviewer fordert Eskalation: "
                             f"{out.get('verdict_reason') or '(kein Grund)'}",
                      question="Der Reviewer braucht eine menschliche "
                               "Entscheidung (s. Grund). Seed schaerfen + "
                               "--resume.")
            break
        # rejected → check stagnation, then iterate
        commit = out.get("commit")
        reason = out.get("verdict_reason")
        if prev_commit is not None and commit == prev_commit:
            escalated = True
            escalation_trigger = "stagnation"
            _escalate(loop_id, "stagnation", round_no, loop_branch, commit,
                      goal, done_criteria, prev_commit,
                      reason="Stagniert: kein neuer Commit gegenueber der "
                             "Vorrunde.",
                      question="Der Bau kommt nicht voran. Seed schaerfen "
                               "(klarere Kriterien) + --resume.")
            break
        # Repeated-reason stagnation only fires on a repeated reason that
        # actually carries signal (see _reason_carries_signal): empty reasons and
        # bare Markdown headings ('## Begründung') would otherwise spuriously
        # escalate after two rejected rounds even while codex makes real,
        # differentiated progress (the same-commit guard above already catches
        # genuine no-progress).
        if (_reason_carries_signal(reason) and _reason_carries_signal(prev_reason)
                and reason == prev_reason):
            escalated = True
            escalation_trigger = "stagnation"
            _escalate(loop_id, "stagnation", round_no, loop_branch, commit,
                      goal, done_criteria, prev_commit,
                      reason=f"Stagniert: Reviewer wiederholt denselben Grund "
                             f"({reason!r}).",
                      question="Derselbe Gap bleibt offen. Seed schaerfen "
                               "+ --resume.")
            break
        prev_commit = commit
        prev_reason = reason
        current_auftrag = (f"{base_auftrag}\n\nDer Reviewer hat abgelehnt. "
                           f"Behebe:\n{reason or '(keine Begruendung)'}")
    else:
        # max-rounds without accepted → escalate with a briefing
        escalated = True
        escalation_trigger = "max_rounds"
        _escalate(loop_id, "max_rounds", max_rounds - 1, loop_branch,
                  final_commit, goal, done_criteria, prev_commit,
                  reason=f"max-rounds ({max_rounds}) erreicht ohne accepted.",
                  question="Mehr Runden noetig? --resume (max_rounds darf "
                           "unveraendert bleiben) oder Seed schaerfen.")
    return _summary()


def run_loop(seed: str, max_rounds: int, adapter: str, round_timeout: int,
             interval: float = 5, b_tick=None, repo: str = "",
             base_branch: str = "main") -> dict:
    """Drive the ping-pong loop. Each round: A works inline on the current
    payload, writes a task to B, waits for B's result (timeout), takes B's
    payload as the next round's input. `b_tick` is an optional callable invoked
    once per round AFTER the task is written (tests use it to run a local B
    poll; in production B is a separate live poller, so b_tick stays None).

    git-building adapters (codex/claude) need a task_id + repo + a STABLE loop
    branch so the built state survives the A->B->A handoff: both A's inline build
    and B's claimed build commit onto bridge/<loop_id> (same continuity mechanism
    as the goal-loop's loop_branch). Non-building adapters (echo/increment) pass
    repo='' and just exchange text payloads — task_id is still supplied (harmless
    for echo, required by codex). Found 2026-06-04: ping-pong had only ever run
    with the echo stub, so the codex runner's task_id/repo requirements broke it.

    Returns a summary dict. fail-safe: on timeout / B-error / runner crash the
    loop aborts cleanly (no hang) and reports the open task_id + last payload."""
    loop_id = _next_loop_id()
    loop_branch = f"bridge/{loop_id}"
    payload = seed
    rounds_done = 0
    aborted = False
    abort_reason = ""
    open_task_id = ""
    workroot = STATE_DIR / "work"

    # git-building adapters (repo set) keep the STANDING seed as the auftrag every
    # round; the work-so-far rides on the loop branch's file state, not on the
    # prose payload. Text adapters (echo/increment, repo='') keep the telephone-
    # game semantics where each side's answer becomes the next input.
    # Found 2026-06-04 live: a 2-round codex ping-pong lost the build seed after
    # round 0 (B received A's prose answer 'Stand ist damit:' instead of the
    # step_<N> instruction and built nothing), so step_2 never appeared (P012).
    building = bool(repo)

    for round_no in range(max_rounds):
        a_payload = ""  # bound even if the A-runner aborts before computing it
        # 1. A works on the current auftrag. For building adapters that is always
        #    the standing seed (continuity via the loop branch); for text adapters
        #    it is the running payload. Build adapters also get the full
        #    task_id/repo/branch/workdir fm; text adapters ignore the extra keys.
        a_auftrag = seed if building else payload
        runner = runners.RUNNERS.get(adapter)
        if runner is None:
            aborted, abort_reason = True, f"unbekannter adapter {adapter!r}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": a_auftrag, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        a_fm = {"task_id": bc.make_task_id(), "payload": a_auftrag,
                "repo": repo, "base_branch": base_branch,
                "branch": loop_branch, "workdir_name": loop_id}
        try:
            a_res = runner(auftrag=a_auftrag, fm=a_fm, workroot=workroot)
        except Exception as exc:  # noqa: BLE001 -- a runner must not crash the loop
            aborted, abort_reason = True, f"A-runner crash: {exc}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": a_auftrag, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        if a_res.status != "done":
            aborted, abort_reason = True, f"A-runner error: {a_res.error_text}"
            append_state(loop_id, {"round": round_no, "side": "A",
                                   "payload_in": a_auftrag, "payload_out": "",
                                   "task_id": "", "status": "error"})
            break
        a_payload = a_res.antwort.strip()

        # 2. Write task to B. For building adapters B must receive the STANDING
        #    seed (so it knows what to build), not A's prose answer — B continues
        #    A's work via the shared loop branch's file state. Text adapters pass
        #    A's computed payload along (telephone game). B builds on the SAME
        #    loop branch so its commit continues A's work, not base.
        b_auftrag = seed if building else a_payload
        task_id = write_round_task(loop_id, round_no, b_auftrag, adapter,
                                   repo=repo, base_branch=base_branch,
                                   loop_branch=loop_branch)
        open_task_id = task_id

        # 3. (tests only) let a local B worker process the task. Pass task_id so
        #    the hook signature matches the goal-loop/build-review b_tick(task_id).
        if b_tick is not None:
            b_tick(task_id)

        # 4. Wait for B's result (per-round timeout -> clean abort).
        fm = wait_for_result(task_id, timeout=round_timeout, interval=interval)
        if fm is None:
            aborted, abort_reason = True, f"timeout in round {round_no}"
            append_state(loop_id, {"round": round_no, "side": "B",
                                   "payload_in": b_auftrag, "payload_out": "",
                                   "task_id": task_id, "status": "timeout"})
            break
        if fm.get("status") == "error":
            aborted, abort_reason = True, f"B error in round {round_no}"
            append_state(loop_id, {"round": round_no, "side": "B",
                                   "payload_in": b_auftrag, "payload_out": "",
                                   "task_id": task_id, "status": "error"})
            break

        b_payload = fm.get("payload", "")
        append_state(loop_id, {"round": round_no, "side": "B",
                               "payload_in": b_auftrag, "payload_out": b_payload,
                               "task_id": task_id, "status": "done"})
        # Building adapters keep the standing seed as next round's auftrag (the
        # built state advances on the loop branch); text adapters feed B's answer
        # back in as the next input.
        if not building:
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
            fm, body = bc.parse_frontmatter(bc.read_text_utf8(path))
            if fm.get("task_id"):  # complete file — a real hit
                # Carry the document body so callers can recover the reviewer's
                # full reasoning (the frontmatter payload is truncated to its
                # first line by parse_frontmatter). Reserved key, never a task
                # field, so it can't collide with a real frontmatter key.
                fm["_body"] = body
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


def validate_resume(loop_id: str, new_seed_text: str | None) -> tuple[bool, str]:
    """Resume validation. max_rounds escalations may resume unchanged (the goal
    is fine, the owner just wants more rounds); every other trigger requires a
    changed/sharpened seed (otherwise the loop runs straight back into the same
    wall). Returns (ok, message)."""
    meta = read_escalation(loop_id)
    if meta is None:
        return (False, f"no ESCALATION file for loop {loop_id}")
    trigger = meta.get("trigger", "")
    if trigger == "max_rounds":
        return (True, "max_rounds: unchanged resume allowed")
    if not new_seed_text or not new_seed_text.strip():
        return (False, f"trigger {trigger!r} requires a sharpened --seed")
    return (True, f"trigger {trigger!r}: sharpened seed provided")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Self-driving A<->B ping-pong loop (runs on Laptop A).")
    parser.add_argument("--seed", default="0", help="Start payload (round 0 input).")
    parser.add_argument("--max-rounds", type=int, required=True,
                        help="Stop after exactly N rounds.")
    parser.add_argument("--adapter", default="increment",
                        choices=["echo", "increment", "codex", "claude"],
                        help="Runner both sides use per round.")
    # Default None -> resolved via config_value() after parse so the precedence
    # chain CLI flag > env > config.json > hardcoded fallback holds. An explicit
    # flag is non-None and wins; omitting it consults config.json then 300/5.0.
    parser.add_argument("--round-timeout", type=int, default=None,
                        help="Max seconds to wait for B's result per round "
                             "(default: config.json round_timeout / env "
                             "DUAL_BRIDGE_ROUND_TIMEOUT / 300).")
    parser.add_argument("--interval", type=float, default=None,
                        help="Poll interval seconds while waiting for a result "
                             "(default: config.json poll_interval / env "
                             "DUAL_BRIDGE_POLL_INTERVAL / 5.0).")
    parser.add_argument("--mode", default="ping-pong",
                        choices=["ping-pong", "build-review", "goal-loop"],
                        help="ping-pong (Stage 1), build-review (Stage 2b), "
                             "or goal-loop (Stage 3).")
    parser.add_argument("--repo", default="",
                        help="Repo URL/path to build in (build-review mode).")
    parser.add_argument("--base-branch", default="main",
                        help="Base branch to start the loop branch from.")
    parser.add_argument("--resume", default=None,
                        help="goal-loop: resume an escalated loop by loop_id "
                             "(reuses the loop branch).")
    args = parser.parse_args(argv)

    # Resolve config-backed defaults (CLI flag wins if given; else env ->
    # config.json -> hardcoded fallback). See bridge_common.config_value.
    if args.round_timeout is None:
        args.round_timeout = bc.config_value(
            "round_timeout", "DUAL_BRIDGE_ROUND_TIMEOUT", 300, cast=int)
    if args.interval is None:
        args.interval = bc.config_value(
            "poll_interval", "DUAL_BRIDGE_POLL_INTERVAL", 5.0, cast=float)

    # Argument validation runs BEFORE the lock (Codex-Verifier MINOR 2026-06-03):
    # a user who forgot --repo must get the actionable "--repo" error, not the
    # "Loop laeuft bereits" lock-conflict message that would otherwise shadow it
    # whenever another loop happens to be running.
    # ping-pong with a git-building adapter also needs a repo (the build commits
    # onto the loop branch). The echo/increment text adapters do not.
    if args.mode == "ping-pong" and args.adapter in ("codex", "claude") and not args.repo:
        print(f"[A] --mode ping-pong --adapter {args.adapter} braucht --repo "
              "(der Build committet auf den Loop-Branch).")
        return 2
    if args.mode in ("build-review", "goal-loop") and not args.repo:
        print(f"[A] --mode {args.mode} braucht --repo.")
        return 2

    # Singleton: one loop driver per machine (reuses the poller lock pattern,
    # local lock file, never the Drive root). Uses a loop-specific lock name.
    lock = bc.default_lock_path().with_name("dual-bridge-loop.lock")
    if not bc.acquire_singleton_lock(lock, must_match="loop_driver"):
        print("[A] Ein Loop-Treiber laeuft bereits -- ich beende mich.")
        return 0

    if args.mode == "build-review":
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

    if args.mode == "goal-loop":
        if args.resume:
            ok, msg = validate_resume(args.resume, args.seed)
            if not ok:
                print(f"[A] resume abgelehnt: {msg}")
                return 2
            loop_id = args.resume
            old = _escalation_path(loop_id)
            if old.exists():
                proc = STATE_DIR / "_processed"
                proc.mkdir(parents=True, exist_ok=True)
                old.replace(proc / old.name)
        else:
            loop_id = None
        try:
            goal, criteria = parse_seed(args.seed)
        except ValueError as exc:
            print(f"[A] ungueltiger Seed: {exc}")
            return 2
        print(f"[A] goal-loop: goal={goal!r} criteria={len(criteria)} "
              f"repo={args.repo} max_rounds={args.max_rounds}")
        summary = run_goal_loop(
            goal=goal, done_criteria=criteria, repo=args.repo,
            base_branch=args.base_branch, max_rounds=args.max_rounds,
            round_timeout=args.round_timeout, interval=args.interval,
            loop_id=loop_id)
        print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
        if summary["accepted"]:
            print(f"    ACCEPTED auf {summary['final_branch']}@"
                  f"{summary['final_commit']}")
            return 0
        if summary["escalated"]:
            print(f"    ESKALIERT ({summary['escalation_trigger']}) — "
                  f"siehe ESCALATION-{summary['loop_id']}.md")
            return 3
        return 1

    print(f"[A] Bridge-Root: {bc.bridge_root()}")
    print(f"[A] Loop: seed={args.seed} max_rounds={args.max_rounds} "
          f"adapter={args.adapter} round_timeout={args.round_timeout}s")
    try:
        summary = run_loop(seed=args.seed, max_rounds=args.max_rounds,
                           adapter=args.adapter,
                           round_timeout=args.round_timeout,
                           interval=args.interval, b_tick=None,
                           repo=args.repo, base_branch=args.base_branch)
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
    bc.ensure_utf8_runtime()
    raise SystemExit(main(sys.argv[1:]))
