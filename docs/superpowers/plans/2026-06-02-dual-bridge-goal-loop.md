# Dual-Bridge Stufe 3 — Goal-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an additive `--mode goal-loop` to the dual-bridge loop driver: a free work-loop toward an open goal with explicit done-criteria, a third `escalate` verdict, four escalation triggers that write an `ESCALATION-<id>.md` and exit nonzero, reseed-resume, and a local deny-first dangerous-action check.

**Architecture:** Builds additively on the Stage-2 `build-review` loop. New mode shares the existing build→review round (`_build_review_round`), but uses a structured seed (goal + done-criteria), a goal-aware review prompt, a third verdict, and routes the existing stagnation/max-rounds aborts plus a new reviewer-`escalate` and dangerous-action trigger into a single escalation writer. No new module — all in `loop_driver.py` + `handoff_poll.py` (`parse_verdict`).

**Tech Stack:** Python 3.11+ stdlib, pytest, fake runners for unit tests (P006/P009: fakes prove mechanics, not contract). conftest.py isolates `DUAL_BRIDGE_ROOT`.

---

## File Structure

- **`scripts/handoff_poll.py`** — `parse_verdict` (shared with orchestrated-bridge gate): additively recognise `escalate`. Fail-closed unchanged.
- **`scripts/loop_driver.py`** — all new goal-loop logic:
  - `parse_seed(seed_text) -> (goal, done_criteria)` — split the structured seed.
  - `write_goal_review_task(...)` — review prompt that judges the diff against done-criteria, allows three markers.
  - `scan_dangerous(text) -> str | None` — local deny-first regex check (patterns mirrored from secret-sweep + a drift test).
  - `write_escalation(loop_id, trigger, round_no, branch, commit, goal, criteria_status, reason, question, progress)` — write `ESCALATION-<loop_id>.md`.
  - `read_escalation(loop_id) -> dict` — parse the frontmatter for resume validation.
  - `run_goal_loop(...)` — the loop; reuses `_build_review_round`, routes 4 triggers to `write_escalation`.
  - `main()` — add `goal-loop` to `--mode` choices + `--resume` arg + resume validation.
- **`scripts/test_goal_loop.py`** — new unit suite (fake runners), mirrors `test_build_review_loop.py` patterns.

**Ground-truth signatures already in the repo (do NOT change):**
- `parse_verdict(text: str) -> tuple[str, str]` at `handoff_poll.py:39` — last `VERDICT:`-line wins, fail-closed to `("rejected", reason)`.
- `_build_review_round(loop_id, round_no, auftrag, repo, base_branch, build_runner, round_timeout, interval=5, b_tick=None) -> dict` with keys `status` (`done|error|timeout`), `verdict`, `verdict_reason`, `commit`, `task_id`, `abort_reason`.
- `RunnerResult(status=, antwort=, branch=, commit=, changed_files=, diff=, verdict=, verdict_reason=, error_text=)` in `runners.py`.
- `run_build_review_loop(...)` returns summary dict with keys `loop_id, rounds_done, accepted, final_commit, aborted, abort_reason, open_task_id, final_branch`.
- Test helper pattern: `_reload_as_a(monkeypatch, tmp_path)` reloads `bridge_common` as endpoint `claude@laptop-a`, reloads `loop_driver`, patches `STATE_DIR = tmp_path`, returns the module. `b_tick(task_id)` is the test hook that simulates B writing a review result.

---

## Task 1: `parse_verdict` recognises `escalate` (fail-closed unchanged)

**Files:**
- Modify: `scripts/handoff_poll.py:60-64`
- Test: `scripts/test_goal_loop.py` (create)

- [ ] **Step 1: Write the failing test**

Create `scripts/test_goal_loop.py`:

```python
"""Goal-loop (Stage 3) unit tests. Fake runners only — fakes prove mechanics,
not contract (P006/P009). conftest.py isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import importlib

import bridge_common as bc


def _reload_as_a(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    return loop_driver


# --- Task 1: parse_verdict escalate ---

def test_parse_verdict_escalate():
    from handoff_poll import parse_verdict
    v, _ = parse_verdict("some reasoning\nVERDICT: escalate")
    assert v == "escalate"


def test_parse_verdict_accepted_unchanged():
    from handoff_poll import parse_verdict
    assert parse_verdict("ok\nVERDICT: accepted")[0] == "accepted"


def test_parse_verdict_rejected_unchanged():
    from handoff_poll import parse_verdict
    assert parse_verdict("nope\nVERDICT: rejected")[0] == "rejected"


def test_parse_verdict_no_marker_fail_closed():
    from handoff_poll import parse_verdict
    assert parse_verdict("no marker here")[0] == "rejected"


def test_parse_verdict_unknown_token_fail_closed():
    from handoff_poll import parse_verdict
    # An unrecognised token must NOT become escalate — fail-closed to rejected.
    assert parse_verdict("x\nVERDICT: maybe")[0] == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_parse_verdict_escalate -v`
Expected: FAIL — `assert 'rejected' == 'escalate'` (current code maps unknown tokens to rejected).

- [ ] **Step 3: Write minimal implementation**

In `handoff_poll.py`, after the `accepted` branch (line 60-61) and before the `rejected` branch, add the `escalate` case. The final block becomes:

```python
    if found == "accepted":
        return ("accepted", "")
    if found == "escalate":
        return ("escalate", "")
    if found == "rejected":
        return ("rejected", "")
    return ("rejected", f"unrecognised verdict token: {found!r}")
```

Also update the docstring line 42-44 to mention `escalate`:

```python
    Convention: the reviewer ends with a line `VERDICT: accepted`,
    `VERDICT: escalate`, or `VERDICT: rejected` (case-insensitive; the LAST
    such line wins). Returns (verdict, reason).
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -v`
Expected: 5 passed (escalate + 4 regression).

- [ ] **Step 5: Run the shared-code regression (gate parser must stay intact)**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_gate_evidence.py test_build_review_loop.py -v`
Expected: all pass (parse_verdict change is additive — accepted/rejected paths unchanged).

- [ ] **Step 6: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/handoff_poll.py scripts/test_goal_loop.py
git commit -m "feat(verdict): parse_verdict recognises escalate (additive, fail-closed)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `parse_seed` — split goal + done-criteria

**Files:**
- Modify: `scripts/loop_driver.py` (add `parse_seed` near the top, after imports)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 2: parse_seed ---

def test_parse_seed_splits_goal_and_criteria(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seed = (
        "## Ziel\n"
        "Add a greeting utility.\n\n"
        "## Done-Kriterien\n"
        "- [ ] function greet(name) returns 'Hello, <name>!'\n"
        "- [ ] has a docstring\n"
    )
    goal, criteria = ld.parse_seed(seed)
    assert goal == "Add a greeting utility."
    assert criteria == [
        "function greet(name) returns 'Hello, <name>!'",
        "has a docstring",
    ]


def test_parse_seed_missing_criteria_raises(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    with __import__("pytest").raises(ValueError):
        ld.parse_seed("## Ziel\nonly a goal, no criteria block\n")


def test_parse_seed_empty_criteria_raises(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    with __import__("pytest").raises(ValueError):
        ld.parse_seed("## Ziel\nG\n\n## Done-Kriterien\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_parse_seed_splits_goal_and_criteria -v`
Expected: FAIL — `AttributeError: module 'loop_driver' has no attribute 'parse_seed'`.

- [ ] **Step 3: Write minimal implementation**

In `loop_driver.py`, add after the imports (before `append_state`):

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k parse_seed -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): parse_seed splits goal + done-criteria

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `write_goal_review_task` — goal-aware review prompt (3 markers)

**Files:**
- Modify: `scripts/loop_driver.py` (add `write_goal_review_task` after `write_review_task`)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 3: write_goal_review_task ---

def test_write_goal_review_task_embeds_criteria_and_three_markers(
        monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    task_id = ld.write_goal_review_task(
        loop_id="loop-x", round_no=0, goal="Add greet util",
        done_criteria=["greet(name) works", "has docstring"],
        loop_branch="bridge/loop-x", loop_commit="c1", diff="+def greet(): ...")
    lane = bc.send_lane()
    path = bc.lane_outbox(lane) / f"task-{task_id}.md"
    text = path.read_text(encoding="utf-8")
    # The review prompt must list the criteria and allow all three markers.
    assert "greet(name) works" in text
    assert "has docstring" in text
    assert "VERDICT: accepted" in text
    assert "VERDICT: rejected" in text
    assert "VERDICT: escalate" in text
    assert "+def greet(): ..." in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_write_goal_review_task_embeds_criteria_and_three_markers -v`
Expected: FAIL — `AttributeError: ... has no attribute 'write_goal_review_task'`.

- [ ] **Step 3: Write minimal implementation**

In `loop_driver.py`, add after `write_review_task` (after line 95):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_write_goal_review_task_embeds_criteria_and_three_markers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): write_goal_review_task judges diff vs done-criteria, 3 markers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `scan_dangerous` — local deny-first check (patterns mirrored from secret-sweep)

**Files:**
- Modify: `scripts/loop_driver.py` (add `scan_dangerous` + `DANGEROUS_PATTERNS`)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 4: scan_dangerous ---

def test_scan_dangerous_flags_force_push(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("git push --force origin main") is not None


def test_scan_dangerous_flags_drop_table(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("DROP TABLE users;") is not None


def test_scan_dangerous_flags_rm_rf(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("rm -rf /home/x") is not None


def test_scan_dangerous_flags_secret(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("token = 'sk-ant-abc123'") is not None


def test_scan_dangerous_clean_passes(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("def greet(name):\n    return f'Hi {name}'") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k scan_dangerous -v`
Expected: FAIL — `AttributeError: ... has no attribute 'scan_dangerous'`.

- [ ] **Step 3: Write minimal implementation**

In `loop_driver.py`, add near the top (after imports, near `parse_seed`):

```python
import re

# Deny-first patterns — mirrored from orchestrated-bridge's secret-sweep
# (gate_secret_sweep.py) + a few destructive shell/SQL patterns. Mirrored, not
# imported, because the gate lives in a separate repo; Task 11 adds a drift test
# that fails if the mirror falls behind. A hit escalates (trigger:
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


def scan_dangerous(text: str) -> str | None:
    """Return the first dangerous pattern found in `text`, or None if clean.
    Deny-first: used by the goal-loop to escalate (NOT block) risky build
    actions/diffs locally, without any cross-device gate roundtrip."""
    if not text:
        return None
    for pat, rx in zip(DANGEROUS_PATTERNS, _DANGEROUS_RE):
        if rx.search(text):
            return pat
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k scan_dangerous -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): scan_dangerous deny-first check (mirrored secret-sweep patterns)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `write_escalation` + `read_escalation` — the escalation file

**Files:**
- Modify: `scripts/loop_driver.py` (add both functions; uses `bc.build_document`, `bc.write_text_utf8`, `bc.parse_document`)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 5: write/read escalation ---

def test_write_and_read_escalation_roundtrip(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    path = ld.write_escalation(
        loop_id="loop-x", trigger="reviewer_requested", round_no=2,
        branch="bridge/loop-x", commit="c2", goal="Add greet util",
        criteria_status=[("greet works", True), ("naming convention", False)],
        reason="Reviewer: naming convention is ambiguous",
        question="Which naming style: snake_case or camelCase?",
        progress="greet() exists on bridge/loop-x@c2")
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "trigger: reviewer_requested" in text
    assert "Which naming style" in text
    assert "- [x] greet works" in text
    assert "- [ ] naming convention" in text

    meta = ld.read_escalation("loop-x")
    assert meta["trigger"] == "reviewer_requested"
    assert meta["loop_id"] == "loop-x"
    assert meta["branch"] == "bridge/loop-x"


def test_read_escalation_missing_returns_none(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.read_escalation("does-not-exist") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_write_and_read_escalation_roundtrip -v`
Expected: FAIL — `AttributeError: ... has no attribute 'write_escalation'`.

- [ ] **Step 3: Write minimal implementation**

First confirm the helper names in `bridge_common` (the worker MUST verify, not assume):

Run: `cd ~/AI/dual-bridge/scripts && grep -n "def build_document\|def parse_document\|def write_text_utf8" bridge_common.py`
Expected: shows `build_document(frontmatter, body)`, a document parser, and `write_text_utf8(path, text)`. If the parser has a different name (e.g. `parse_frontmatter`/`read_document`), use that name in `read_escalation` below.

In `loop_driver.py`, add (escalation files live in `STATE_DIR`, alongside the loop JSONL):

```python
def _escalation_path(loop_id: str):
    return STATE_DIR / f"ESCALATION-{loop_id}.md"


def write_escalation(loop_id: str, trigger: str, round_no: int, branch: str,
                     commit: str, goal: str,
                     criteria_status: list[tuple[str, bool]], reason: str,
                     question: str, progress: str):
    """Write ESCALATION-<loop_id>.md (the durable escalation artefact). Returns
    the path. `criteria_status` is a list of (criterion, met) pairs."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fm = {
        "loop_id": loop_id, "trigger": trigger, "round": str(round_no),
        "branch": branch, "commit": commit, "exit_reason": "escalation",
        "created": bc.now_iso(),
    }
    crit_lines = "\n".join(
        f"- [{'x' if met else ' '}] {name}" for name, met in criteria_status)
    body = (
        f"## Ziel (aus dem Seed)\n{goal}\n\n"
        f"## Done-Kriterien — Stand\n{crit_lines}\n\n"
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
    fm, _body = bc.parse_document(path.read_text(encoding="utf-8"))
    return fm
```

NOTE: if Step-3 grep showed the parser is named differently, replace `bc.parse_document(...)` with the actual function. If it returns only frontmatter (not a tuple), adjust to `fm = bc.<parser>(...)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k escalation -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): write/read ESCALATION-<id>.md (durable escalation artefact)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `run_goal_loop` happy path — accepted ends the loop

**Files:**
- Modify: `scripts/loop_driver.py` (add `run_goal_loop`)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 6: run_goal_loop accepted ---

def _fake_build_factory(commit_seq):
    """Return a fake build_runner that yields commits from commit_seq in order."""
    from runners import RunnerResult
    calls = {"i": 0}

    def fake_build(auftrag, fm, workroot):
        i = calls["i"]
        calls["i"] += 1
        commit = commit_seq[min(i, len(commit_seq) - 1)]
        return RunnerResult(status="done", antwort="built", branch=fm["branch"],
                            commit=commit, changed_files=["greet.py"],
                            diff="+def greet(name): return f'Hi {name}'")
    return fake_build


def _b_verdict(verdict, reason="r"):
    """Return a b_tick that writes a review result with the given verdict."""
    def tick(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": verdict, "verdict_reason": reason}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nVERDICT: {verdict}\n"))
    return tick


def test_goal_loop_accepted_round_one(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    summary = ld.run_goal_loop(
        goal="Add greet util", done_criteria=["greet works"],
        repo="r", base_branch="main", max_rounds=3, round_timeout=5,
        interval=1, build_runner=_fake_build_factory(["c1"]),
        b_tick=_b_verdict("accepted"))
    assert summary["accepted"] is True
    assert summary["escalated"] is False
    assert summary["final_commit"] == "c1"
    assert summary["final_branch"].startswith("bridge/loop-")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_goal_loop_accepted_round_one -v`
Expected: FAIL — `AttributeError: ... has no attribute 'run_goal_loop'`.

- [ ] **Step 3: Write minimal implementation**

In `loop_driver.py`, add after `run_build_review_loop` (after line 214). This first version handles accepted + the loop scaffold; later tasks add the escalation branches.

```python
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
        if out["status"] != "done":
            # transport/build failure — treat as stagnation-style escalation
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
        # (escalate / stagnation / dangerous handled in later tasks)
        prev_commit = out.get("commit")
        reason = out.get("verdict_reason")
        prev_reason = reason
        current_auftrag = (f"{base_auftrag}\n\nDer Reviewer hat abgelehnt. "
                           f"Behebe:\n{reason or '(keine Begruendung)'}")
    return _summary()
```

Also add a thin goal-aware round wrapper (mirrors `_build_review_round` but uses the goal review prompt). Add after `_build_review_round` (after line 138):

```python
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
    return {"status": "done", "abort_reason": "",
            "verdict": fm_result.get("verdict"),
            "verdict_reason": fm_result.get("verdict_reason"),
            "commit": a_res.commit, "diff": a_res.diff or "", "task_id": task_id}
```

And a small `_escalate` helper that maps loop state to `write_escalation` (criteria status is best-effort here: all-unmet unless a later task tracks it — for the scaffold mark all unmet). Add before `run_goal_loop`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_goal_loop_accepted_round_one -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): run_goal_loop scaffold + accepted path + goal round wrapper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: rejected iterates; reviewer-`escalate` escalates

**Files:**
- Modify: `scripts/loop_driver.py` (`run_goal_loop` loop body)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 7: rejected iterates, escalate escalates ---

def test_goal_loop_rejected_then_accepted_iterates(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    verdicts = iter(["rejected", "accepted"])

    def b_seq(task_id):
        v = next(verdicts)
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": v, "verdict_reason": f"reason-{v}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nVERDICT: {v}\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2"]), b_tick=b_seq)
    assert summary["accepted"] is True
    assert summary["rounds_done"] == 2


def test_goal_loop_reviewer_escalate(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["ambiguous one"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1"]),
        b_tick=_b_verdict("escalate", reason="criterion is ambiguous"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "reviewer_requested"
    assert summary["accepted"] is False
    meta = ld.read_escalation(summary["loop_id"])
    assert meta["trigger"] == "reviewer_requested"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_goal_loop_reviewer_escalate -v`
Expected: FAIL — `escalated` is False (no escalate branch yet) / KeyError on trigger.

- [ ] **Step 3: Write minimal implementation**

In `run_goal_loop`, replace the `# (escalate / stagnation / dangerous handled in later tasks)` placeholder and the rejected tail with the escalate branch. The block after `if out["verdict"] == "accepted": ... break` becomes:

```python
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
        # rejected → iterate (stagnation guards added in Task 8)
        prev_commit = out.get("commit")
        reason = out.get("verdict_reason")
        prev_reason = reason
        current_auftrag = (f"{base_auftrag}\n\nDer Reviewer hat abgelehnt. "
                           f"Behebe:\n{reason or '(keine Begruendung)'}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k "iterates or reviewer_escalate" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): rejected iterates, reviewer escalate writes escalation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: stagnation + max-rounds escalate (with context)

**Files:**
- Modify: `scripts/loop_driver.py` (`run_goal_loop` loop body + the `for/else`)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 8: stagnation + max-rounds ---

def test_goal_loop_stagnation_same_commit(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # Same commit twice + always rejected → stagnation on round 2.
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=5, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c1"]),
        b_tick=_b_verdict("rejected", reason="nope"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "stagnation"


def test_goal_loop_stagnation_repeated_reason(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # New commit each round but identical reject reason → stagnation.
    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=5, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2", "c3"]),
        b_tick=_b_verdict("rejected", reason="same gap"))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "stagnation"


def test_goal_loop_max_rounds(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    # Distinct commits + distinct reasons → never stagnates, hits max-rounds.
    reasons = iter(["r1", "r2"])

    def b_distinct(task_id):
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "from": "claude@laptop-b",
              "to": "claude@laptop-a", "status": "done", "task_id": task_id,
              "kind": "review", "verdict": "rejected",
              "verdict_reason": next(reasons)}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, "## Antwort\nVERDICT: rejected\n"))

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=2, round_timeout=5, interval=1,
        build_runner=_fake_build_factory(["c1", "c2"]), b_tick=b_distinct)
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "max_rounds"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k "stagnation or max_rounds" -v`
Expected: FAIL — no stagnation/max-rounds escalation branch yet.

- [ ] **Step 3: Write minimal implementation**

Add stagnation guards in the rejected tail, and a `for/else` for max-rounds. The rejected tail becomes:

```python
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
        if prev_reason is not None and reason == prev_reason:
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
```

NOTE (structure — read carefully): in Task 6 the function body is `for round_no in range(max_rounds): <body>` immediately followed by `return _summary()`. Python requires `else:` to attach directly to the `for` with NOTHING between them. So: (1) keep the `for` line and its body, (2) replace the rejected tail inside the body as shown above, (3) delete the standalone `return _summary()` that followed the loop, (4) add the `else:` block shown above (indented to the `for`, not the body), (5) add a fresh `return _summary()` AFTER the `else:` block. After this edit the shape is: `for ...: <body with breaks>` / `else: <max-rounds escalation>` / `return _summary()`. Verify by eye that `else:` lines up under `for`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k "stagnation or max_rounds" -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full goal-loop suite so far**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -v`
Expected: all green (Tasks 1-8).

- [ ] **Step 6: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): stagnation + max-rounds escalate with context

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: dangerous-action escalates (deny-first on the diff)

**Files:**
- Modify: `scripts/loop_driver.py` (`run_goal_loop` — check the diff after a successful build, before review)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 9: dangerous-action ---

def test_goal_loop_dangerous_diff_escalates(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    bc.ensure_dirs()
    from runners import RunnerResult

    def dangerous_build(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="built", branch=fm["branch"],
                            commit="c1", changed_files=["x.sql"],
                            diff="+DROP TABLE users;")

    # b_tick should never fire — escalation happens before review.
    fired = {"n": 0}

    def b_should_not_run(task_id):
        fired["n"] += 1

    summary = ld.run_goal_loop(
        goal="G", done_criteria=["c"], repo="r", base_branch="main",
        max_rounds=3, round_timeout=5, interval=1,
        build_runner=dangerous_build, b_tick=b_should_not_run)
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "dangerous_action"
    assert fired["n"] == 0
    meta = ld.read_escalation(summary["loop_id"])
    assert meta["trigger"] == "dangerous_action"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_goal_loop_dangerous_diff_escalates -v`
Expected: FAIL — no dangerous check yet, the loop would proceed to review (`fired["n"] == 1`).

- [ ] **Step 3: Write minimal implementation**

The diff is produced inside `_goal_build_review_round` *before* the review task is written. The cleanest seam: scan in the round wrapper and short-circuit. In `_goal_build_review_round`, right after the `a_res.status != "done"` guard and BEFORE `write_goal_review_task`, add:

```python
    danger = scan_dangerous((a_res.diff or "") + "\n" + auftrag)
    if danger is not None:
        return {"status": "dangerous", "abort_reason": f"dangerous: {danger}",
                "verdict": None, "verdict_reason": None,
                "commit": a_res.commit, "diff": a_res.diff or "", "task_id": "",
                "danger": danger}
```

Then in `run_goal_loop`, handle the new `dangerous` status. Change the `if out["status"] != "done":` block to branch on dangerous first:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py::test_goal_loop_dangerous_diff_escalates -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): dangerous-action escalates before review (deny-first diff scan)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: CLI — `--mode goal-loop`, `--resume`, resume validation

**Files:**
- Modify: `scripts/loop_driver.py` (`main`, lines ~331-401)
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the failing tests**

Append to `scripts/test_goal_loop.py`:

```python
# --- Task 10: CLI + resume validation ---

def test_main_goal_loop_requires_repo(monkeypatch, tmp_path, capsys):
    ld = _reload_as_a(monkeypatch, tmp_path)
    rc = ld.main(["--mode", "goal-loop", "--max-rounds", "2",
                  "--seed", "## Ziel\nG\n\n## Done-Kriterien\n- [ ] c\n"])
    assert rc == 2
    assert "repo" in capsys.readouterr().out.lower()


def test_resume_max_rounds_allows_unchanged(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    # Pre-seed an escalation file with trigger max_rounds.
    ld.write_escalation(
        loop_id="loop-r", trigger="max_rounds", round_no=1, branch="bridge/loop-r",
        commit="c1", goal="G", criteria_status=[("c", False)],
        reason="max", question="more?", progress="p")
    # validate_resume returns (ok, message); max_rounds → ok even unchanged.
    ok, _msg = ld.validate_resume("loop-r", new_seed_text=None)
    assert ok is True


def test_resume_other_trigger_requires_changed_seed(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    ld.write_escalation(
        loop_id="loop-s", trigger="stagnation", round_no=1, branch="bridge/loop-s",
        commit="c1", goal="G", criteria_status=[("c", False)],
        reason="stuck", question="sharpen?", progress="p")
    ok, _msg = ld.validate_resume("loop-s", new_seed_text=None)
    assert ok is False  # stagnation requires a sharpened seed
    ok2, _msg2 = ld.validate_resume(
        "loop-s", new_seed_text="## Ziel\nG2\n\n## Done-Kriterien\n- [ ] c2\n")
    assert ok2 is True


def test_resume_missing_escalation_fails(monkeypatch, tmp_path):
    ld = _reload_as_a(monkeypatch, tmp_path)
    ok, _msg = ld.validate_resume("no-such-loop", new_seed_text=None)
    assert ok is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k "resume or goal_loop_requires_repo" -v`
Expected: FAIL — `validate_resume` missing / `goal-loop` not a valid `--mode` choice.

- [ ] **Step 3: Write minimal implementation**

First add `validate_resume` in `loop_driver.py` (before `main`):

```python
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
```

Then wire the CLI. Add `goal-loop` to the `--mode` choices (line 344-346):

```python
    parser.add_argument("--mode", default="ping-pong",
                        choices=["ping-pong", "build-review", "goal-loop"],
                        help="ping-pong (Stage 1), build-review (Stage 2b), "
                             "or goal-loop (Stage 3).")
    parser.add_argument("--resume", default=None,
                        help="goal-loop: resume an escalated loop by loop_id "
                             "(reuses the loop branch).")
```

Add a `goal-loop` branch in `main`, after the `build-review` branch (after line ~384, before the ping-pong default):

```python
    if args.mode == "goal-loop":
        if not args.repo:
            print("[A] --mode goal-loop braucht --repo.")
            return 2
        if args.resume:
            ok, msg = validate_resume(args.resume, args.seed)
            if not ok:
                print(f"[A] resume abgelehnt: {msg}")
                return 2
            loop_id = args.resume
            # move the consumed escalation out of the way
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
            round_timeout=args.round_timeout, loop_id=loop_id)
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
```

NOTE: verify the existing `--seed`, `--repo`, `--base-branch`, `--round-timeout` args exist (they do, from build-review). The `goal-loop` branch reuses them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k "resume or requires_repo" -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_goal_loop.py
git commit -m "feat(goal-loop): CLI --mode goal-loop + --resume with trigger-aware validation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Drift test — mirrored dangerous patterns must not fall behind secret-sweep

**Files:**
- Test: `scripts/test_goal_loop.py`

- [ ] **Step 1: Write the test (it documents + guards the mirror)**

The secret-sweep source lives in the *separate* orchestrated-bridge repo, which may not be present on every machine. The drift test is therefore conditional: it skips cleanly if the source file is absent, but fails loudly if present and a secret pattern is missing from our mirror. Append to `scripts/test_goal_loop.py`:

```python
# --- Task 11: drift guard for mirrored dangerous patterns ---

def test_dangerous_patterns_cover_secret_marker(monkeypatch, tmp_path):
    """Our mirror MUST at least catch the sk-ant- secret marker that secret-sweep
    catches. This is the one pattern that overlaps by contract."""
    ld = _reload_as_a(monkeypatch, tmp_path)
    assert ld.scan_dangerous("sk-ant-deadbeef") is not None


def test_dangerous_patterns_drift_vs_secret_sweep(monkeypatch, tmp_path):
    """If orchestrated-bridge's gate_secret_sweep.py is reachable, every literal
    'sk-ant' / 'api_key' marker it relies on must also be covered by our mirror.
    Skips if the source repo isn't checked out on this machine."""
    import os
    import pytest
    ld = _reload_as_a(monkeypatch, tmp_path)
    candidates = [
        os.path.expanduser(
            "~/AI/Agents/demos/orchestrated-loop/src/orchestrated_loop/"
            "gate_secret_sweep.py"),
    ]
    src = next((p for p in candidates if os.path.exists(p)), None)
    if src is None:
        pytest.skip("orchestrated-bridge secret-sweep source not present")
    text = open(src, encoding="utf-8").read()
    # Contractual overlap markers — if secret-sweep references them, we must too.
    for marker in ("sk-ant", "api_key"):
        if marker in text:
            probe = {"sk-ant": "sk-ant-x", "api_key": "api_key = 'x'"}[marker]
            assert ld.scan_dangerous(probe) is not None, (
                f"mirror drifted: secret-sweep covers {marker!r} but our "
                f"DANGEROUS_PATTERNS does not")
```

- [ ] **Step 2: Run the test**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest test_goal_loop.py -k dangerous_patterns -v`
Expected: `test_dangerous_patterns_cover_secret_marker` PASS; the drift test PASS or SKIP (skip is acceptable — source repo may be absent).

- [ ] **Step 3: Commit**

```bash
cd ~/AI/dual-bridge
git add scripts/test_goal_loop.py
git commit -m "test(goal-loop): drift guard for mirrored secret-sweep patterns (skips if source absent)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Full-suite regression + push

**Files:** none (verification only)

- [ ] **Step 1: Run the FULL dual-bridge suite**

Run: `cd ~/AI/dual-bridge/scripts && python -m pytest -v`
Expected: all green — the new `test_goal_loop.py` PLUS every existing suite (`test_stage1`, `test_hardening`, `test_build_review_loop`, `test_loop_driver`, `test_loop_continuity_realgit`, `test_lanes`, `test_gate_evidence`, `test_codex_branch_override`, `test_claude_adapter`, `test_latency_probe`). Stage 1 + build-review must be regression-free.

- [ ] **Step 2: Confirm no production-DB / Drive-isolation risk**

This project writes to Google Drive in production. Confirm conftest isolation held: the suite must NOT have created files under `G:\Meine Ablage\...`. Run:

Run: `cd ~/AI/dual-bridge && git status --short`
Expected: only `scripts/loop_driver.py`, `scripts/handoff_poll.py`, `scripts/test_goal_loop.py`, and the two doc files show up (already committed). No stray `state/`, no Drive paths. If anything unexpected appears, STOP and investigate (global rule 3 / file-isolation).

- [ ] **Step 3: Push (only after the user confirms)**

Per session rules, push only on explicit user confirmation. Ask first, then:

```bash
cd ~/AI/dual-bridge
git push origin main
```

- [ ] **Step 4: Report**

Summarise: tasks done, total test count, what the live-proof (separate session step) still needs. Do NOT claim the live-proof is done — that's the next, separate step (see plan tail).

---

## After the unit plan: Live-Proof (separate step — NOT in the unit suite, P007)

The unit suite proves mechanics with fakes (P006/P009). The contract — that a real
codex builds, a real claude reviews against the criteria, and the escalation fires on a
genuinely ambiguous criterion — is proven separately, cross-device, exactly like Stage 1/2:

1. Write a seed against `dual-bridge` itself as a throwaway target, with 2-3 done-criteria,
   one deliberately under-specified/ambiguous (e.g. "the utility follows the project's
   naming convention" without saying which).
2. Start B's reviewer poller (`handoff_poll.py --watch`).
3. Run `loop_driver.py --mode goal-loop --repo <throwaway> --max-rounds 4 --seed <seed.md>`.
4. Expect: 1-2 rounds of real progress (reviewer ticks criteria, rejects with concrete gaps),
   then a `VERDICT: escalate` on the ambiguous criterion → `ESCALATION-<id>.md` written, exit 3.
5. Ground-truth verify (P007 — read the artefacts, don't trust status): branch content
   byte-exact vs remote, the real `VERDICT:` marker in the reviewer's result text, the B-device
   claim, and read `ESCALATION-<id>.md` by hand (correct trigger, the ambiguous criterion
   unmet, a sensible owner question).
6. Then reseed-resume: sharpen the ambiguous criterion, `--resume <loop-id> --seed <sharpened>`,
   confirm codex builds on the SAME branch (continuity) and the loop can now reach `accepted`.

This proves both paths in one run (progress + escalation) plus the reseed-resume — the full
Stage-3 contract.
