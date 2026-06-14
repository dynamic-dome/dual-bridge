"""Stage-1 self-driving A<->B ping-pong loop driver (runs on Laptop A).

A is the conductor: it does its own work step inline (local runner), writes a
task into the A->B lane, waits for B's result (with a per-round timeout), then
takes B's payload into the next round. B stays the unchanged handoff_poll worker.

Loop state/history lives A-side in scripts/state/LOOP-<loop_id>.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import bridge_common as bc
import runners  # noqa: F401 -- registers echo + increment
import codex_adapter  # noqa: F401
import adapter_git
import claude_adapter  # noqa: F401
import claude_build  # noqa: F401 -- registers claude-build
import codex_review_adapter  # noqa: F401 -- registers codex-review (reviewer)

def _state_dir() -> Path:
    """A-side loop state/history dir (LOOP-*.jsonl, ESCALATION-*.md, work/).

    Resolved LAZILY from DUAL_BRIDGE_STATE on every call -- NEVER frozen as an
    import-time module constant (CLAUDE.md rule 3.4: a frozen path ignores env
    overrides and survives delenv+reload teardowns, which is exactly how loop
    tests leaked real LOOP-*.jsonl into the live scripts/state/, #7923). Same
    DUAL_BRIDGE_STATE convention as bridge_status/bridge_metrics/etc.; the state
    is a LOCAL path, deliberately NOT under DUAL_BRIDGE_ROOT (the Drive root)."""
    override = os.environ.get("DUAL_BRIDGE_STATE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "state"


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


def parse_relay_seed(seed_text: str) -> tuple[str, list[str]]:
    """Split a relay-loop seed into (ziel, leitplanken).

    Format:
        ## Ziel
        <prose, open direction — concrete to vague>
        ## Leitplanken      (optional)
        - constraint 1
        - [ ] constraint 2

    `ziel` is the prose under '## Ziel'. `leitplanken` are the bullet/checklist
    items under '## Leitplanken' (a leading '- ' and optional '[ ]'/'[x]' are
    stripped). Leitplanken may be empty/absent (the 'völlig offen' case). Raises
    ValueError if '## Ziel' is missing or empty."""
    ziel_lines: list[str] = []
    leitplanken: list[str] = []
    section = None
    for raw in seed_text.splitlines():
        line = raw.rstrip()
        low = line.strip().lower()
        if low.startswith("## ziel"):
            section = "ziel"
            continue
        if low.startswith("## leitplanken"):
            section = "leitplanken"
            continue
        if section == "ziel" and line.strip():
            ziel_lines.append(line.strip())
        elif section == "leitplanken":
            stripped = line.strip()
            if stripped.startswith("- "):
                item = stripped[2:].strip()
                if item[:3] in ("[ ]", "[x]", "[X]"):
                    item = item[3:].strip()
                if item:
                    leitplanken.append(item)
    ziel = " ".join(ziel_lines).strip()
    if not ziel:
        raise ValueError("relay seed has no '## Ziel' block")
    return ziel, leitplanken


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

# Destructive-SQL patterns that are LEGITIMATE inside test files (a test wipes
# the conftest-isolated tmp DB on purpose) but dangerous in production code. These
# are suppressed only for tests/ diff sections; secret/force-push/rm-rf are NOT in
# this set and stay armed everywhere. False-Positive 2026-06-08, DCO-LAGE-001
# #5d10: a `_reset()` helper's bare `DELETE FROM events` tripped the guard.
_SQL_DESTRUCTIVE_PATS = frozenset({
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
})
# A unified-diff target-path header (`+++ b/<path>` or `+++ <path>`). The `b/`
# prefix is git's default; tolerate its absence (e.g. --no-prefix).
_DIFF_TARGET_RE = re.compile(r"^\+\+\+\s+(?:b/)?(\S+)", re.MULTILINE)
# A diff section boundary — git emits one `diff --git` line per file.
_DIFF_GIT_RE = re.compile(r"^diff --git ", re.MULTILINE)


def _is_test_path(path: str) -> bool:
    """True if `path` is a test file/dir (cleanup SQL there hits the isolated tmp
    DB, not production). Matches a top-level or nested `tests/` segment and the
    `test_*.py` / `*_test.py` naming convention."""
    p = path.replace("\\", "/").lstrip("./")
    return (
        p.startswith("tests/")
        or "/tests/" in p
        or p.rsplit("/", 1)[-1].startswith("test_")
        or p.rsplit("/", 1)[-1].endswith("_test.py")
    )


_DELETE_FROM_PAT = r"\bDELETE\s+FROM\b"
_DELETE_FROM_RE = re.compile(_DELETE_FROM_PAT, re.IGNORECASE)
# A row-targeted CRUD delete: `DELETE FROM <tbl> WHERE ... <placeholder>` where
# the predicate is bound (`?`, `:name`, `%s`, `%(name)s`). This is the OPPOSITE
# of the destructive mass-delete the guard exists to stop — a bound placeholder
# means a specific row, not a table wipe. False-Positive 2026-06-07: the
# reminders-v2 goal-loop escalated in round 0 on a legit `delete(id)` method.
# (?s): `.` spans newlines so a line-wrapped `DELETE FROM x\n WHERE id = ?`
# statement still reads as one safe shape.
_CRUD_DELETE_RE = re.compile(
    r"(?s)\bDELETE\s+FROM\b.*\bWHERE\b.*(?:\?|:\w+|%\(\w+\)s|%s)",
    re.IGNORECASE,
)
# Strip SQL line-comments so a `DELETE FROM users; -- WHERE id = ?` cannot
# launder a table wipe by hiding a fake placeholder in a comment.
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _delete_from_is_safe(text: str) -> bool:
    """True only if EVERY `DELETE FROM` statement in `text` is the safe,
    parametrised single-row CRUD shape.

    Reasons per SQL statement (split on `;`), NOT per text line, so that a
    line-wrapped CRUD delete is not a false-positive AND a mass-delete in a
    second statement on the same line (or a trailing-comment bypass) cannot be
    masked by a safe sibling. One bare/unparametrised DELETE FROM makes the
    whole text unsafe."""
    cleaned = _SQL_LINE_COMMENT_RE.sub("", text)
    saw_delete = False
    for stmt in cleaned.split(";"):
        if _DELETE_FROM_RE.search(stmt):
            saw_delete = True
            if not _CRUD_DELETE_RE.search(stmt):
                return False
    return saw_delete


def _scan_segment(text: str, allow_destructive_sql: bool) -> str | None:
    """Scan one body of text against every dangerous pattern. When
    `allow_destructive_sql` is True (a tests/ diff section), destructive-SQL
    patterns are skipped — secret/force-push/rm-rf stay armed regardless."""
    for pat, rx in zip(DANGEROUS_PATTERNS, _DANGEROUS_RE):
        if rx.search(text):
            # Allow legitimate parametrised CRUD deletes through the otherwise
            # bare DELETE-FROM guard (the pattern stays in DANGEROUS_PATTERNS for
            # the drift mirror; the exception lives here, not in the list).
            if pat == _DELETE_FROM_PAT and _delete_from_is_safe(text):
                continue
            # In a test file, a bare table wipe is isolated cleanup, not a prod
            # delete — suppress only the destructive-SQL family there.
            if allow_destructive_sql and pat in _SQL_DESTRUCTIVE_PATS:
                continue
            return pat
    return None


def scan_dangerous(text: str) -> str | None:
    """Return the first dangerous pattern found in `text`, or None if clean.
    Deny-first: used by the goal-loop to escalate (NOT block) risky build
    actions/diffs locally, without any cross-device gate roundtrip.

    Diff-aware: when `text` is a unified diff, it is split per file section and a
    destructive-SQL hit under a tests/ path is suppressed (cleanup against the
    conftest-isolated tmp DB), while the same hit in a production path still
    escalates. Non-diff text (raw SQL/prose) is scanned as one prod-grade
    segment — unchanged behaviour."""
    if not text:
        return None
    # Not a unified diff -> scan whole thing as production-grade (no allowance).
    if not _DIFF_GIT_RE.search(text):
        return _scan_segment(text, allow_destructive_sql=False)
    # Split into per-file sections at each `diff --git` boundary, decide the
    # tests/ allowance from each section's `+++ b/<path>` target header.
    bounds = [m.start() for m in _DIFF_GIT_RE.finditer(text)]
    bounds.append(len(text))
    # Any preamble before the first `diff --git` (rare) is prod-grade.
    if bounds[0] > 0:
        hit = _scan_segment(text[:bounds[0]], allow_destructive_sql=False)
        if hit is not None:
            return hit
    for start, end in zip(bounds, bounds[1:]):
        section = text[start:end]
        target = _DIFF_TARGET_RE.search(section)
        is_test = bool(target) and _is_test_path(target.group(1))
        hit = _scan_segment(section, allow_destructive_sql=is_test)
        if hit is not None:
            return hit
    return None


def append_state(loop_id: str, record: dict) -> None:
    """Append one round record to scripts/state/LOOP-<loop_id>.jsonl (history,
    A-side only). Adds an ISO timestamp. Append-only, never deletes."""
    _state_dir().mkdir(parents=True, exist_ok=True)
    record = dict(record, ts=bc.now_iso())
    path = _state_dir() / f"LOOP-{loop_id}.jsonl"
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
        "status": "open", "task_id": task_id,
        "kind": "implement" if repo else "echo",
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
                      loop_branch: str, loop_commit: str, diff: str = "",
                      reviewer: str = "claude") -> str:
    """Write an open kind:review task to the reviewer endpoint. The reviewer runs
    headless WITHOUT tools, so it cannot check out the branch — we embed the
    build diff in the prompt and have it judge the diff text. `reviewer` is the
    adapter name (claude | codex-review); default claude keeps old behaviour."""
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
        "adapter": reviewer,
        "loop_id": loop_id, "round": str(round_no),
        "loop_branch": loop_branch, "loop_commit": loop_commit,
        "payload": f"{loop_branch}@{loop_commit}",
        "claimed_by": "", "claimed_at": "",
    }
    diff_block = diff.strip() or "(kein Diff — der Bau-Agent meldete keine Datei-Aenderung)"
    body = (f"## Auftrag\n{auftrag}\n\n"
            f"Der Bau-Agent hat auf `{loop_branch}` (Commit `{loop_commit}`) "
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
                           loop_commit: str, diff: str = "",
                           reviewer: str = "claude") -> str:
    """Write a goal-loop kind:review task to the reviewer endpoint. The reviewer
    judges the diff against the explicit done-criteria and answers with one of
    THREE markers: accepted (all criteria met), escalate (needs a human
    decision), or rejected (gaps remain). Tool-less reviewer → diff embedded in
    the prompt. `reviewer` is the adapter name (claude | codex-review)."""
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
        "adapter": reviewer,
        "loop_id": loop_id, "round": str(round_no),
        "loop_branch": loop_branch, "loop_commit": loop_commit,
        "payload": f"{loop_branch}@{loop_commit}",
        "claimed_by": "", "claimed_at": "",
    }
    diff_block = diff.strip() or "(kein Diff — der Bau-Agent meldete keine Datei-Aenderung)"
    crit_block = "\n".join(f"- [ ] {c}" for c in done_criteria)
    body = (
        f"## Ziel\n{goal}\n\n"
        f"## Done-Kriterien\n{crit_block}\n\n"
        f"Der Bau-Agent hat auf `{loop_branch}` (Commit `{loop_commit}`) "
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


def write_relay_review_task(loop_id: str, round_no: int, ziel: str,
                            leitplanken: list[str], loop_branch: str,
                            loop_commit: str, diff: str = "",
                            reviewer: str = "claude") -> str:
    """Write a relay-loop kind:review task. The reviewer judges whether the diff
    is a sensible, correct, self-contained EXTENSION toward `ziel` (honoring
    leitplanken) and answers with one of three markers. escalate has a double
    role here: 'no sensible extension left' (saturation) OR an owner
    direction/risk decision. Tool-less reviewer → diff embedded in the prompt.
    `reviewer` is the adapter name (claude | codex-review)."""
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
        "adapter": reviewer,
        "loop_id": loop_id, "round": str(round_no),
        "loop_branch": loop_branch, "loop_commit": loop_commit,
        "payload": f"{loop_branch}@{loop_commit}",
        "claimed_by": "", "claimed_at": "",
    }
    diff_block = diff.strip() or "(kein Diff — der Bau-Agent meldete keine Erweiterung)"
    lp_block = ("\n".join(f"- {c}" for c in leitplanken)
                if leitplanken else "(keine — freie Richtung)")
    body = (
        f"## Ziel\n{ziel}\n\n"
        f"## Leitplanken\n{lp_block}\n\n"
        f"Der Bau-Agent hat auf `{loop_branch}` (Commit `{loop_commit}`) EINEN "
        "Erweiterungsschritt gebaut. Hier ist NUR der Diff dieses Schritts gegen "
        "den vorigen Stand. Du hast KEINE Tools — beurteile den Diff-Text direkt.\n\n"
        f"```diff\n{diff_block}\n```\n\n"
        "Ist dies eine sinnvolle, korrekte, in sich abgeschlossene Erweiterung "
        "Richtung Ziel (Leitplanken eingehalten)? Schreibe zuerst eine kurze "
        "Begruendung, und als ALLERLETZTE Zeile NUR einen der drei Marker:\n"
        "`VERDICT: accepted`   (guter Schritt — behalten, der andere baut weiter)\n"
        "`VERDICT: rejected`   (Schritt mangelhaft — Bau soll nachbessern)\n"
        "`VERDICT: escalate`   (KEINE sinnvolle Erweiterung mehr moeglich = fertig, "
        "ODER eine Richtungs-/Risiko-Entscheidung fuer den Owner)\n"
        "Die Verdikt-Zeile darf NICHTS ausser dem Marker enthalten.\n\n"
        "## Ergebnis\n<wird vom Reviewer gefuellt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def _build_review_round(loop_id, round_no, auftrag, repo, base_branch,
                        build_runner, round_timeout, interval=5, b_tick=None,
                        reviewer="claude"):
    """One build→review round. A builds via build_runner (codex), writes a
    kind:review task to B, waits for B's verdict. Returns an outcome dict.
    `b_tick(task_id)` is a test hook; in production B is a separate poller."""
    loop_branch = f"bridge/{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch,
          "workdir_name": loop_id}
    workroot = _state_dir() / "work"
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
                                diff=a_res.diff or "", reviewer=reviewer)
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
                             interval=5, b_tick=None, reviewer="claude"):
    """One goal-loop build→review round. Like _build_review_round but the review
    task lists the done-criteria (write_goal_review_task)."""
    loop_branch = f"bridge/{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch,
          "workdir_name": loop_id}
    workroot = _state_dir() / "work"
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
    # Scan the generated DIFF only — never the auftrag. The guard protects against
    # dangerous GENERATED CODE; the auftrag (seed + the prior round's reviewer
    # reason) is input text, not an executed action. A reviewer who merely talks
    # about SQL ("die Fixture fuehrt ein DELETE FROM aus") would otherwise trip the
    # guard once that prose lands in round 1's auftrag (False-Positive 2026-06-07,
    # reminders Paket A). Seed safety is the seed author's responsibility.
    danger = scan_dangerous(a_res.diff or "")
    if danger is not None:
        return {"status": "dangerous", "abort_reason": f"dangerous: {danger}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": "",
                "danger": danger}
    task_id = write_goal_review_task(loop_id, round_no, goal, done_criteria,
                                     loop_branch, a_res.commit or "",
                                     diff=a_res.diff or "", reviewer=reviewer)
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


def _relay_build_prompt(ziel: str, leitplanken: list[str], feedback: str = "") -> str:
    """Builder instruction for one relay step. `feedback` carries the prior
    round's reviewer reason on a reject."""
    lp = ("\n".join(f"- {c}" for c in leitplanken)
          if leitplanken else "(keine — freie Richtung)")
    parts = [
        f"## Ziel\n{ziel}",
        f"## Leitplanken\n{lp}",
        ("Der bisherige Stand liegt auf dem aktuellen Branch. Erweitere ihn um "
         "GENAU EINEN in sich abgeschlossenen, sinnvollen Schritt Richtung Ziel. "
         "Halte die Leitplanken ein. Wenn nichts Sinnvolles mehr hinzuzufuegen "
         "ist, aendere NICHTS (leerer Commit/keine Aenderung) und begruende das "
         "kurz."),
    ]
    if feedback:
        parts.append(f"## Reviewer-Feedback der Vorrunde (nachbessern)\n{feedback}")
    return "\n\n".join(parts)


def _relay_increment_diff(workdir, prev_commit, fallback_diff: str) -> str:
    """Diff of THIS round's step. Prefer the real increment (prev_commit...HEAD)
    when we have a prior commit AND the workdir exists (real run); otherwise fall
    back to the builder's reported diff (first round, or unit tests with a fake
    builder and no git workdir). Never raises."""
    try:
        if prev_commit and workdir is not None and Path(workdir).exists():
            inc = adapter_git._git_diff_since(Path(workdir), prev_commit)
            if inc.strip():
                return inc
    except Exception:  # noqa: BLE001 — diff is best-effort; fall back, never crash
        pass
    return fallback_diff or ""


def _relay_round(loop_id, round_no, ziel, leitplanken, builder_adapter, reviewer,
                 build_runner, prev_commit, repo, base_branch, round_timeout,
                 interval=5, b_tick=None):
    """One relay round: build one step → dangerous-scan → review the INCREMENT.
    Returns an outcome dict. Mirrors _goal_build_review_round; differences:
    increment diff for review, saturation on empty build diff, builder/reviewer
    carried in the outcome."""
    loop_branch = f"bridge/{loop_id}"
    fm = {"task_id": bc.make_task_id(), "repo": repo,
          "base_branch": base_branch, "branch": loop_branch,
          "workdir_name": loop_id}
    workroot = _state_dir() / "work"
    workdir = workroot / loop_id
    base = {"builder": builder_adapter, "reviewer": reviewer,
            "verdict": None, "verdict_reason": None, "commit": prev_commit,
            "diff": "", "saturated": False, "task_id": ""}
    try:
        a_res = build_runner(auftrag=_relay_build_prompt(ziel, leitplanken),
                             fm=fm, workroot=workroot)
    except Exception as exc:  # noqa: BLE001 — a runner must not crash the loop
        return {**base, "status": "error", "abort_reason": f"A-build crash: {exc}"}
    if a_res.status != "done":
        return {**base, "status": "error",
                "abort_reason": f"A-build error: {a_res.error_text}"}

    # Empty build diff = the builder found nothing sensible to add → saturation.
    if not (a_res.diff or "").strip():
        return {**base, "status": "done", "abort_reason": "", "saturated": True,
                "commit": a_res.commit or prev_commit, "diff": ""}

    danger = scan_dangerous(a_res.diff or "")
    if danger is not None:
        return {**base, "status": "dangerous", "abort_reason": f"dangerous: {danger}",
                "commit": a_res.commit, "diff": a_res.diff or "", "danger": danger}

    inc = _relay_increment_diff(workdir, prev_commit, a_res.diff or "")
    task_id = write_relay_review_task(loop_id, round_no, ziel, leitplanken,
                                      loop_branch, a_res.commit or "",
                                      diff=inc, reviewer=reviewer)
    if b_tick is not None:
        b_tick(task_id)
    fm_result = wait_for_result(task_id, timeout=round_timeout, interval=interval)
    if fm_result is None:
        return {**base, "status": "timeout",
                "abort_reason": f"timeout in round {round_no}",
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}
    if fm_result.get("status") == "error":
        return {**base, "status": "error",
                "abort_reason": f"B error in round {round_no}",
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}
    reason = fm_result.get("verdict_reason")
    if not _reason_carries_signal(reason):
        body_reason = _reason_from_body(fm_result.get("_body"))
        reason = body_reason or fm_result.get("payload") or reason or ""
    return {**base, "status": "done", "abort_reason": "",
            "verdict": fm_result.get("verdict"), "verdict_reason": reason,
            "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}


def _is_conflict_copy(name: str) -> bool:
    # Same heuristic as handoff_poll._is_conflict_copy / handoff_collect.
    return "(" in name and ")" in name


def _next_loop_id() -> str:
    return f"loop-{bc.make_task_id()}"


def run_build_review_loop(auftrag, repo, base_branch, max_rounds,
                          round_timeout, interval=5, build_runner=None,
                          b_tick=None, reviewer="claude"):
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
            round_timeout=round_timeout, interval=interval, b_tick=b_tick,
            reviewer=reviewer)
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
    return _state_dir() / f"ESCALATION-{loop_id}.md"


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
    _state_dir().mkdir(parents=True, exist_ok=True)
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


def _reviewer_adapter(reviewer: str | None, builder_adapter: str | None) -> str:
    """Pick the reviewer adapter (Stufe A, Option 3: auto-default + override).

    Explicit `--reviewer` wins and maps the CLI value to the registered adapter
    name ('codex' -> 'codex-review', 'claude' -> 'claude'). When omitted (None),
    auto-select the OPPOSITE model of the builder so the build is always judged by
    the other model: a claude-build build is reviewed by codex-review; everything
    else (codex/echo/increment/None builder) keeps the claude reviewer — that is
    the historical default, so codex-builds still go to claude unchanged."""
    if reviewer == "codex":
        return "codex-review"
    if reviewer == "claude":
        return "claude"
    if builder_adapter == "claude-build":
        return "codex-review"
    return "claude"


def _other_builder(adapter: str) -> str:
    """The opposite builder for relay rotation. codex <-> claude-build."""
    return "claude-build" if adapter == "codex" else "codex"


def _goal_build_runner(adapter: str | None):
    """Builder selection for goal-loop mode.

    Historically the goal-loop ALWAYS built via codex — `--adapter` was passed in
    but ignored for the A-side builder. That is exactly why the echo·echo smoke
    preset could never be accepted: codex (not echo) built, and an empty/garbage
    smoke build was rejected → max_rounds escalation (#7903 / L20). Route
    adapter=='echo' to the marker-building echo runner so the smoke exercises the
    full pipeline. Route adapter=='claude-build' to the claude builder so the
    symmetric loop (claude baut / codex reviewt) works in goal-loop mode too — it
    is a REAL git builder (commits a branch+diff), so the "no text-only runner as
    builder" guard does not apply. Every other adapter (incl. the 'increment' CLI
    default, the text-only 'claude' reviewer, and any unknown value) keeps the
    codex default: the goal-loop assumes a real git builder, and a non-building
    text runner must not silently slip in as builder.
    Returns None to mean 'use run_goal_loop's codex default' (unchanged path)."""
    if adapter == "echo":
        return runners.RUNNERS["echo"]
    if adapter == "claude-build":
        return runners.RUNNERS["claude-build"]
    return None


def run_goal_loop(goal, done_criteria, repo, base_branch, max_rounds,
                  round_timeout, interval=5, build_runner=None, b_tick=None,
                  loop_id=None, merge_on_accept=False, reviewer="claude"):
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
    merged = False
    merge_error = ""
    escalation_pushed = False

    def _summary():
        return {
            "loop_id": loop_id, "rounds_done": rounds_done, "accepted": accepted,
            "escalated": escalated, "escalation_trigger": escalation_trigger,
            "final_commit": final_commit, "final_branch": loop_branch,
            "merged": merged, "merge_error": merge_error,
            "escalation_pushed": escalation_pushed,
        }

    for round_no in range(max_rounds):
        out = _goal_build_review_round(
            loop_id=loop_id, round_no=round_no, goal=goal,
            done_criteria=done_criteria, auftrag=current_auftrag, repo=repo,
            base_branch=base_branch, build_runner=build_runner,
            round_timeout=round_timeout, interval=interval, b_tick=b_tick,
            reviewer=reviewer)
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
            # Integrate the accepted build into base so the NEXT package's fresh
            # clone sees it (cross-package accumulation). Opt-in: an experimental
            # loop must not silently push to master. Fail-soft: a merge conflict /
            # push reject is recorded but never downgrades the accepted verdict —
            # the work succeeded, only its integration didn't (visible in summary).
            if merge_on_accept:
                workdir = _state_dir() / "work" / loop_id
                try:
                    new_base = adapter_git.merge_accepted_to_base(
                        repo=repo, branch=loop_branch, base_branch=base_branch,
                        workdir=workdir)
                    merged = True
                    append_state(loop_id, {"round": round_no, "side": "merge",
                                           "merged_into": base_branch,
                                           "base_head": new_base,
                                           "status": "done"})
                except Exception as exc:  # noqa: BLE001 — never crash on merge
                    merge_error = str(exc)
                    append_state(loop_id, {"round": round_no, "side": "merge",
                                           "merged_into": base_branch,
                                           "status": "error",
                                           "error": merge_error})
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

    # On ANY escalation trigger, push the loop branch to origin so the DCO-side
    # 'Prüfen & Mergen' button can fetch + gate-check it. One place catches all
    # six triggers (each sets escalated=True + break). Best-effort: a failed push
    # never downgrades the escalation — the DCO button falls back to a manual
    # hint. Mirrors the accept-push credential handling.
    if escalated:
        workdir = _state_dir() / "work" / loop_id
        try:
            escalation_pushed = adapter_git.push_branch_on_escalation(
                repo=repo, branch=loop_branch, workdir=workdir)
        except Exception:  # noqa: BLE001 — never crash on the escalation push
            escalation_pushed = False
    return _summary()


# ---------------------------------------------------------------------------
# Stufe B: relay-loop (codex <-> claude-build, abwechselnd mit Gegenmodell-Review)
# ---------------------------------------------------------------------------

def _relay_runner_with_feedback(runner, ziel, leitplanken, feedback):
    """Wrap a build runner so its `auftrag` is the relay build prompt (with the
    prior reject feedback). Keeps _relay_round agnostic of prompt construction."""
    prompt = _relay_build_prompt(ziel, leitplanken, feedback)
    def run(auftrag, fm, workroot):  # auftrag from _relay_round is ignored; we own it
        return runner(auftrag=prompt, fm=fm, workroot=workroot)
    return run


def run_relay_loop(ziel, leitplanken, repo, base_branch, max_rounds,
                   round_timeout, interval=5, start_adapter="codex",
                   build_runner_for=None, b_tick=None, loop_id=None):
    """Collaborative extension loop (Stufe B). Two models alternately build one
    sensible step each on a shared accumulating branch and review each other
    (reviewer = opposite model). Builder rotates on `accepted`; on `rejected` the
    same builder retries with the reviewer's feedback. Ends on saturation (clean
    success), owner-escalate, dangerous, or max_rounds. Returns a summary dict."""
    if build_runner_for is None:
        import runners as _runners
        def build_runner_for(adapter):
            return _runners.RUNNERS[adapter]
    if loop_id is None:
        loop_id = _next_loop_id()
    loop_branch = f"bridge/{loop_id}"
    builder_adapter = start_adapter
    prev_commit = None
    prev_reason = ""
    rounds_done = 0
    accepted = False
    saturated = False
    escalated = False
    escalation_trigger = ""
    final_commit = ""

    def _summary():
        return {"loop_id": loop_id, "rounds_done": rounds_done,
                "accepted": accepted, "saturated": saturated,
                "escalated": escalated, "escalation_trigger": escalation_trigger,
                "final_commit": final_commit, "final_branch": loop_branch}

    for round_no in range(max_rounds):
        reviewer = _reviewer_adapter(None, builder_adapter)
        out = _relay_round(
            loop_id=loop_id, round_no=round_no, ziel=ziel,
            leitplanken=leitplanken, builder_adapter=builder_adapter,
            reviewer=reviewer,
            build_runner=_relay_runner_with_feedback(
                build_runner_for(builder_adapter), ziel, leitplanken, prev_reason),
            prev_commit=prev_commit, repo=repo, base_branch=base_branch,
            round_timeout=round_timeout, interval=interval, b_tick=b_tick)
        append_state(loop_id, {"round": round_no, "side": "relay",
                               "builder": out["builder"], "reviewer": out["reviewer"],
                               "verdict": out.get("verdict"),
                               "verdict_reason": out.get("verdict_reason"),
                               "commit": out.get("commit"),
                               "saturated": out.get("saturated"),
                               "status": out["status"]})
        final_commit = out.get("commit") or final_commit

        if out["status"] == "dangerous":
            escalated = True
            escalation_trigger = "dangerous_action"
            _escalate(loop_id, "dangerous_action", round_no, loop_branch,
                      out.get("commit") or "", ziel, leitplanken,
                      prev_commit, out.get("danger", ""), "")
            break
        if out["status"] != "done":
            # build/review error or timeout — stop with the reason, no escalation file.
            escalation_trigger = out.get("abort_reason", out["status"])
            break
        if out.get("saturated"):
            saturated = True
            accepted = True  # nothing sensible left = clean success
            break

        verdict = out.get("verdict")
        if verdict == "accepted":
            rounds_done += 1
            prev_commit = out.get("commit")
            prev_reason = ""
            builder_adapter = _other_builder(builder_adapter)  # rotate on accept
            accepted = True
        elif verdict == "escalate":
            escalated = True
            escalation_trigger = "reviewer_requested"
            _escalate(loop_id, "reviewer_requested", round_no, loop_branch,
                      out.get("commit") or "", ziel, leitplanken,
                      prev_commit, out.get("verdict_reason") or "", "")
            break
        else:  # rejected (or unknown) → same builder retries with feedback
            rounds_done += 1
            prev_reason = out.get("verdict_reason") or ""
            accepted = False

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
    workroot = _state_dir() / "work"

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
                        choices=["echo", "increment", "codex", "claude", "claude-build"],
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
                        choices=["ping-pong", "build-review", "goal-loop", "relay-loop"],
                        help="ping-pong (Stage 1), build-review (Stage 2b), "
                             "goal-loop (Stage 3), or relay-loop (Stufe B: beide "
                             "bauen abwechselnd, Gegenmodell reviewt).")
    parser.add_argument("--repo", default="",
                        help="Repo URL/path to build in (build-review mode).")
    parser.add_argument("--base-branch", default="main",
                        help="Base branch to start the loop branch from.")
    parser.add_argument("--resume", default=None,
                        help="goal-loop: resume an escalated loop by loop_id "
                             "(reuses the loop branch).")
    parser.add_argument("--merge-on-accept", action="store_true",
                        help="goal-loop: on accepted, merge the loop branch into "
                             "--base-branch and push it, so the next package's "
                             "fresh clone sees this build (cross-package "
                             "accumulation). Fail-soft on conflict.")
    parser.add_argument("--reviewer", default=None, choices=["claude", "codex"],
                        help="Who reviews the build (build-review/goal-loop). "
                             "Default: auto = the opposite model of the builder "
                             "(claude-build -> codex reviews; codex -> claude "
                             "reviews). Set explicitly to override.")
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
    if args.mode == "ping-pong" and args.adapter in ("codex", "claude", "claude-build") and not args.repo:
        print(f"[A] --mode ping-pong --adapter {args.adapter} braucht --repo "
              "(der Build committet auf den Loop-Branch).")
        return 2
    if args.mode in ("build-review", "goal-loop", "relay-loop") and not args.repo:
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
                interval=args.interval, build_runner=None, b_tick=None,
                reviewer=_reviewer_adapter(args.reviewer, "codex"))
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
        print(f"    History: {_state_dir() / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
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
                proc = _state_dir() / "_processed"
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
            build_runner=_goal_build_runner(args.adapter),
            loop_id=loop_id, merge_on_accept=args.merge_on_accept,
            reviewer=_reviewer_adapter(args.reviewer, args.adapter))
        print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
        if summary["accepted"]:
            print(f"    ACCEPTED auf {summary['final_branch']}@"
                  f"{summary['final_commit']}")
            if args.merge_on_accept:
                if summary.get("merged"):
                    print(f"    MERGED -> {args.base_branch} (naechstes Paket "
                          f"sieht diesen Build)")
                else:
                    print(f"    NICHT GEMERGT: {summary.get('merge_error') or '?'} "
                          f"(accepted bleibt gueltig; Branch manuell mergen)")
            return 0
        if summary["escalated"]:
            print(f"    ESKALIERT ({summary['escalation_trigger']}) — "
                  f"siehe ESCALATION-{summary['loop_id']}.md")
            return 3
        return 1

    if args.mode == "relay-loop":
        start = args.adapter if args.adapter in ("codex", "claude-build") else "codex"
        try:
            ziel, leitplanken = parse_relay_seed(args.seed)
        except ValueError as exc:
            print(f"[A] ungueltiger relay-Seed: {exc}")
            return 2
        print(f"[A] relay-loop: ziel={ziel!r} leitplanken={len(leitplanken)} "
              f"start={start} repo={args.repo} max_rounds={args.max_rounds}")
        summary = run_relay_loop(
            ziel=ziel, leitplanken=leitplanken, repo=args.repo,
            base_branch=args.base_branch, max_rounds=args.max_rounds,
            round_timeout=args.round_timeout, interval=args.interval,
            start_adapter=start, build_runner_for=None, b_tick=None)
        print("=" * 60)
        print(f"[A] relay-loop {summary['loop_id']} fertig.")
        print(f"    Runden: {summary['rounds_done']}/{args.max_rounds}")
        print(f"    Saettigung: {summary['saturated']} | Eskaliert: {summary['escalated']}")
        print(f"    Branch: {summary['final_branch']} @ {summary['final_commit']}")
        print(f"    History: {_state_dir() / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
        print("=" * 60)
        if summary["escalated"]:
            return 3
        return 0

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
    print(f"    History: {_state_dir() / ('LOOP-' + summary['loop_id'] + '.jsonl')}")
    print("=" * 60)
    return 1 if summary["aborted"] else 0


if __name__ == "__main__":
    bc.ensure_utf8_runtime()
    raise SystemExit(main(sys.argv[1:]))
