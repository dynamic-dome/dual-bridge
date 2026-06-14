# Relay-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein neuer Bridge-Modus `--mode relay-loop`, in dem codex und claude-build abwechselnd je einen sinnvollen Schritt auf einem akkumulierenden Branch bauen und sich gegenseitig (Gegenmodell) gegenlesen, bis Sättigung, Owner-Eskalation, dangerous oder max_rounds.

**Architecture:** Eigene `run_relay_loop` in `scripts/loop_driver.py`, parallel zu goal-loop. Bau-Rolle rotiert bei `accepted` (codex ↔ claude-build), Reviewer ist immer das Gegenmodell via `_reviewer_adapter`. Wiederverwendet `finalize_build`, `scan_dangerous`, Eskalations-/State-Maschinerie. Neuer Inkrement-Diff-Helper, damit der Reviewer nur den Schritt dieser Runde sieht.

**Tech Stack:** Python 3.12 stdlib, pytest, bestehende dual-bridge-Bausteine (`adapter_git`, `runners`, `bridge_common`).

**Spec:** `docs/superpowers/specs/2026-06-14-relay-loop-design.md`. Offene Punkte dort final entschieden: **O1** `--reviewer` wird im relay-loop schlicht ignoriert (Gegenmodell ist konstitutiv; help-Text sagt „nur build-review/goal-loop"). **O2** Inkrement-Diff via neuem `_git_diff_since` + Fallback auf `a_res.diff`, durch Task 1 + Task 5 testabgesichert.

---

## File Structure

- **`scripts/adapter_git.py`** (modify) — neuer Helper `_git_diff_since(workdir, since_ref)` neben `_git_diff`.
- **`scripts/loop_driver.py`** (modify) — `parse_relay_seed`, `_other_builder`, `write_relay_review_task`, `_relay_increment_diff`, `_relay_round`, `run_relay_loop`, CLI-Zweig `relay-loop`.
- **`scripts/test_relay_loop.py`** (create) — alle Unit-Tests für den Modus.
- **`scripts/test_finalize_build.py`** (modify) — Test für `_git_diff_since`.
- **`docs/live-proofs/stageB-relay-loop.md`** (create, Task 8) — Real-Binary-Beweis.

Konventionen: Tests laufen `cd scripts && python -X utf8 -m pytest`. Isolation ist automatisch (conftest autouse: tmp ROOT/STATE/LOCK, Endpoint `claude@laptop-a`, Runner-Re-Registrierung). Tests setzen den Builder per `build_runner_for`-Injektion + `b_tick`-Hook (kein echtes codex/claude), genau wie `test_goal_loop.py`.

---

## Task 1: Inkrement-Diff-Helper `_git_diff_since`

**Files:**
- Modify: `scripts/adapter_git.py` (nach `_git_diff`, ~Zeile 518)
- Test: `scripts/test_finalize_build.py`

- [ ] **Step 1: Write the failing test**

In `scripts/test_finalize_build.py` ergänzen (nutzt das vorhandene git-Repo-Setup-Muster der Datei; falls die Datei einen `_init_repo`/`tmp`-Helper hat, diesen verwenden — sonst inline wie hier):

```python
def test_git_diff_since_shows_only_increment(tmp_path):
    import subprocess
    import adapter_git
    wd = tmp_path / "repo"
    wd.mkdir()
    def git(*a):
        subprocess.run(["git", *a], cwd=wd, check=True,
                       capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (wd / "a.txt").write_text("step1\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "s1")
    first = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wd,
                           capture_output=True, text=True).stdout.strip()
    (wd / "b.txt").write_text("step2\n", encoding="utf-8")
    git("add", "."); git("commit", "-q", "-m", "s2")
    diff = adapter_git._git_diff_since(wd, first)
    assert "b.txt" in diff and "step2" in diff
    assert "a.txt" not in diff  # increment only, not the whole history
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_finalize_build.py::test_git_diff_since_shows_only_increment -v`
Expected: FAIL — `AttributeError: module 'adapter_git' has no attribute '_git_diff_since'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/adapter_git.py` direkt nach `_git_diff` (vor `_tail`):

```python
def _git_diff_since(workdir: Path, since_ref: str) -> str:
    """Unified diff of what was added since `since_ref` (since_ref...HEAD).

    The relay-loop uses this so the reviewer judges only THIS round's increment,
    not the whole accumulated branch (which grows every round). Same _DIFF_LIMIT
    truncation as _git_diff (never a silent cap)."""
    cp = _run_git(workdir, "diff", f"{since_ref}...HEAD")
    text = cp.stdout or ""
    if len(text) > _DIFF_LIMIT:
        text = (text[:_DIFF_LIMIT]
                + f"\n\n[... Diff bei {_DIFF_LIMIT} Zeichen abgeschnitten "
                  f"(Gesamtlaenge {len(cp.stdout)}); Reviewer urteilt auf dem "
                  "gezeigten Ausschnitt ...]\n")
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_finalize_build.py::test_git_diff_since_shows_only_increment -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/adapter_git.py scripts/test_finalize_build.py
git commit -m "feat(adapter_git): _git_diff_since fuer Inkrement-Diff (relay-loop)"
```

---

## Task 2: Seed-Parser `parse_relay_seed`

**Files:**
- Modify: `scripts/loop_driver.py` (neben `parse_seed`)
- Test: `scripts/test_relay_loop.py` (create)

- [ ] **Step 1: Write the failing test**

Neue Datei `scripts/test_relay_loop.py`:

```python
"""Relay-loop tests. Isoliert via conftest (tmp ROOT/STATE/LOCK, Endpoint A,
Runner re-registriert). Builder werden injiziert (build_runner_for) + b_tick-Hook,
kein echtes codex/claude."""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import bridge_common as bc
import pytest


def test_parse_relay_seed_ziel_and_leitplanken():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed(
        "## Ziel\nEine CLI-Toolsammlung.\n\n## Leitplanken\n- nur stdlib\n- [ ] mit Test\n")
    assert ziel == "Eine CLI-Toolsammlung."
    assert lp == ["nur stdlib", "mit Test"]


def test_parse_relay_seed_ziel_only():
    import loop_driver
    ziel, lp = loop_driver.parse_relay_seed("## Ziel\nFreie Richtung.\n")
    assert ziel == "Freie Richtung." and lp == []


def test_parse_relay_seed_missing_ziel_raises():
    import loop_driver
    with pytest.raises(ValueError):
        loop_driver.parse_relay_seed("## Leitplanken\n- x\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py -v`
Expected: FAIL — `AttributeError: module 'loop_driver' has no attribute 'parse_relay_seed'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/loop_driver.py` direkt nach `parse_seed`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): parse_relay_seed (Ziel + optionale Leitplanken)"
```

---

## Task 3: Rotations-Helper `_other_builder`

**Files:**
- Modify: `scripts/loop_driver.py` (neben `_reviewer_adapter`)
- Test: `scripts/test_relay_loop.py`

- [ ] **Step 1: Write the failing test**

In `scripts/test_relay_loop.py` ergänzen:

```python
def test_other_builder_rotates_codex_and_claude():
    import loop_driver
    assert loop_driver._other_builder("codex") == "claude-build"
    assert loop_driver._other_builder("claude-build") == "codex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_other_builder_rotates_codex_and_claude -v`
Expected: FAIL — `AttributeError: ... '_other_builder'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/loop_driver.py` direkt nach `_reviewer_adapter`:

```python
def _other_builder(adapter: str) -> str:
    """The opposite builder for relay rotation. codex <-> claude-build."""
    return "claude-build" if adapter == "codex" else "codex"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_other_builder_rotates_codex_and_claude -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): _other_builder Rotations-Helper"
```

---

## Task 4: Review-Task-Writer `write_relay_review_task`

**Files:**
- Modify: `scripts/loop_driver.py` (nach `write_goal_review_task`)
- Test: `scripts/test_relay_loop.py`

- [ ] **Step 1: Write the failing test**

In `scripts/test_relay_loop.py` ergänzen:

```python
def test_write_relay_review_task_fields_and_reviewer(tmp_path, monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    tid = loop_driver.write_relay_review_task(
        "loop-r", 2, "Eine CLI-Toolsammlung.", ["nur stdlib"],
        "bridge/loop-r", "deadbeef", diff="--- a\n+++ b\n+x\n",
        reviewer="codex-review")
    doc = (bc.lane_outbox(bc.send_lane()) / f"task-{tid}.md").read_text(encoding="utf-8")
    fm, body = bc.parse_frontmatter(doc)
    assert fm["adapter"] == "codex-review"
    assert fm["kind"] == "review"
    # Body nennt Ziel + Leitplanken + die drei Marker, NICHT 'Done-Kriterien'.
    assert "Eine CLI-Toolsammlung." in body and "nur stdlib" in body
    assert "VERDICT: accepted" in body and "VERDICT: escalate" in body
    assert "Done-Kriterien" not in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_write_relay_review_task_fields_and_reviewer -v`
Expected: FAIL — `AttributeError: ... 'write_relay_review_task'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/loop_driver.py` direkt nach `write_goal_review_task`. Spiegelt dessen `fm`-Aufbau exakt (gleiche Header-Felder), nur der Body unterscheidet sich (Ziel/Leitplanken statt Done-Kriterien, escalate-Doppelrolle):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_write_relay_review_task_fields_and_reviewer -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): write_relay_review_task (Ziel/Leitplanken statt Done-Kriterien)"
```

---

## Task 5: Eine Runde `_relay_round` (+ Inkrement-Diff-Wahl)

**Files:**
- Modify: `scripts/loop_driver.py` (nach `_goal_build_review_round`)
- Test: `scripts/test_relay_loop.py`

Diese Runde spiegelt `_goal_build_review_round`, mit drei Unterschieden: (a) Builder/Reviewer werden als Adapter-Namen übergeben (Rotation passiert im Loop), (b) der Review-Diff ist der **Inkrement** (via `_relay_increment_diff`), (c) Sättigung wird erkannt (leerer Build-Diff). Das `outcome`-Dict trägt zusätzlich `saturated` und `builder`/`reviewer`.

- [ ] **Step 1: Write the failing test**

In `scripts/test_relay_loop.py` ergänzen. Fake-Builder gibt ein `RunnerResult`; der Reviewer wird via `b_tick` simuliert, indem ein Result mit Verdikt in B's inbox gelegt wird. Wir nutzen denselben Mechanismus wie `test_goal_loop.py` (dort `_reload_as_a` + ein b_tick, der ein Result schreibt). Hier ein kompakter Helper:

```python
from runners import RunnerResult


def _reload_as_a(monkeypatch, tmp_path):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    return loop_driver


def _fake_builder(commit, diff="--- a\n+++ b\n+x\n"):
    def run(auftrag, fm, workroot):
        return RunnerResult(status="done", antwort="gebaut", branch=fm.get("branch"),
                            commit=commit, diff=diff)
    return run


def _verdict_b_tick(ld, verdict):
    """Return a b_tick that answers the just-written review task with `verdict`."""
    def tick(task_id):
        lane = bc.send_lane()
        # The review task is in our OUTbox (A->B). Write B's result into A's inbox.
        fm = {"created": bc.now_iso(), "schema_version": "2",
              "task_id": task_id, "status": "done", "kind": "review",
              "verdict": verdict, "verdict_reason": f"reason-{verdict}"}
        body = f"## Antwort\nok\nVERDICT: {verdict}\n"
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, body))
    return tick


def test_relay_round_accepted_returns_verdict_and_commit(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    out = ld._relay_round(
        loop_id="loop-r", round_no=0, ziel="Z", leitplanken=[],
        builder_adapter="codex", reviewer="claude",
        build_runner=_fake_builder("c0"), prev_commit=None,
        repo="r", base_branch="main", round_timeout=2, interval=1,
        b_tick=_verdict_b_tick(ld, "accepted"))
    assert out["status"] == "done"
    assert out["verdict"] == "accepted"
    assert out["commit"] == "c0"
    assert out["saturated"] is False


def test_relay_round_empty_diff_is_saturation(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    out = ld._relay_round(
        loop_id="loop-r", round_no=1, ziel="Z", leitplanken=[],
        builder_adapter="codex", reviewer="claude",
        build_runner=_fake_builder("c0", diff=""), prev_commit="c0",
        repo="r", base_branch="main", round_timeout=2, interval=1,
        b_tick=lambda tid: None)
    assert out["saturated"] is True
    assert out["status"] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_relay_round_accepted_returns_verdict_and_commit test_relay_loop.py::test_relay_round_empty_diff_is_saturation -v`
Expected: FAIL — `AttributeError: ... '_relay_round'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/loop_driver.py` zuerst der Inkrement-Diff-Helper (nach `_goal_build_review_round`), dann `_relay_round`:

```python
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
```

Und der Build-Prompt-Helper (vor `_relay_round`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py -v`
Expected: alle bisherigen PASS (inkl. die 2 neuen `_relay_round`-Tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): _relay_round + Inkrement-Diff + Saettigungs-Erkennung"
```

---

## Task 6: Der Loop `run_relay_loop`

**Files:**
- Modify: `scripts/loop_driver.py` (nach `run_goal_loop`)
- Test: `scripts/test_relay_loop.py`

- [ ] **Step 1: Write the failing tests**

In `scripts/test_relay_loop.py` ergänzen. Wir steuern Builder über `build_runner_for` (Map adapter→runner) und Verdikte über eine `b_tick`-Sequenz:

```python
def _seq_b_tick(ld, verdicts):
    """b_tick that answers each successive review task with the next verdict."""
    state = {"i": 0}
    def tick(task_id):
        v = verdicts[min(state["i"], len(verdicts) - 1)]
        state["i"] += 1
        lane = bc.send_lane()
        fm = {"created": bc.now_iso(), "schema_version": "2", "task_id": task_id,
              "status": "done", "kind": "review", "verdict": v,
              "verdict_reason": f"reason-{v}"}
        bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                           bc.build_document(fm, f"## Antwort\nx\nVERDICT: {v}\n"))
    return tick


def _runner_map(commits):
    """build_runner_for: each call returns the next commit id, alternating none."""
    state = {"i": 0}
    def for_adapter(adapter):
        def run(auftrag, fm, workroot):
            c = commits[min(state["i"], len(commits) - 1)]
            state["i"] += 1
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=c, diff="" if c is None else f"+{c}\n")
        return run
    return for_adapter


def test_relay_loop_rotates_builder_on_accept(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seen = []
    def for_adapter(adapter):
        seen.append(adapter)
        def run(auftrag, fm, workroot):
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=f"c{len(seen)}", diff=f"+{len(seen)}\n")
        return run
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=2,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=for_adapter, b_tick=_seq_b_tick(ld, ["accepted", "accepted"]))
    # Round 0 builder=codex, round 1 builder=claude-build (rotated on accept).
    assert seen[0] == "codex" and seen[1] == "claude-build"
    assert summary["rounds_done"] == 2


def test_relay_loop_no_rotation_on_reject(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    seen = []
    def for_adapter(adapter):
        seen.append(adapter)
        def run(auftrag, fm, workroot):
            return RunnerResult(status="done", antwort="b", branch=fm.get("branch"),
                                commit=f"c{len(seen)}", diff=f"+{len(seen)}\n")
        return run
    ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=2,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=for_adapter, b_tick=_seq_b_tick(ld, ["rejected", "accepted"]))
    # reject keeps the same builder for round 1.
    assert seen[0] == "codex" and seen[1] == "codex"


def test_relay_loop_saturation_clean_stop(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=5,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=_runner_map([None]),  # empty diff round 0
        b_tick=lambda tid: None)
    assert summary["saturated"] is True
    assert summary["escalated"] is False
    assert summary["accepted"] is True  # saturation = clean success


def test_relay_loop_escalate_writes_escalation(tmp_path, monkeypatch):
    ld = _reload_as_a(monkeypatch, tmp_path)
    summary = ld.run_relay_loop(
        ziel="Z", leitplanken=[], repo="r", base_branch="main", max_rounds=3,
        round_timeout=2, interval=1, start_adapter="codex",
        build_runner_for=_runner_map(["c0", "c1"]),
        b_tick=_seq_b_tick(ld, ["escalate"]))
    assert summary["escalated"] is True
    assert summary["escalation_trigger"] == "reviewer_requested"
    assert ld._escalation_path(summary["loop_id"]).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py -k relay_loop -v`
Expected: FAIL — `AttributeError: ... 'run_relay_loop'`

- [ ] **Step 3: Write minimal implementation**

In `scripts/loop_driver.py` nach `run_goal_loop`. Folgt der Struktur von `run_goal_loop` (State-Mirror, Eskalations-/Summary-Maschinerie), aber rotiert den Builder und kennt die Sättigung. `build_runner_for(adapter)` liefert den Runner für einen Adapternamen (Default: `runners.RUNNERS[adapter]`).

```python
def run_relay_loop(ziel, leitplanken, repo, base_branch, max_rounds,
                   round_timeout, interval=5, start_adapter="codex",
                   build_runner_for=None, b_tick=None, loop_id=None):
    """Collaborative extension loop (Stufe B). Two models alternately build one
    sensible step each on a shared accumulating branch and review each other
    (reviewer = opposite model). Builder rotates on `accepted`; on `rejected` the
    same builder retries with the reviewer's feedback. Ends on saturation (clean
    success), owner-escalate, dangerous, or max_rounds. Returns a summary dict."""
    if build_runner_for is None:
        def build_runner_for(adapter):
            return runners.RUNNERS[adapter]
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
        auftrag_extra = prev_reason  # reject feedback flows into the next build
        out = _relay_round(
            loop_id=loop_id, round_no=round_no, ziel=ziel,
            leitplanken=leitplanken, builder_adapter=builder_adapter,
            reviewer=reviewer,
            build_runner=_relay_runner_with_feedback(
                build_runner_for(builder_adapter), ziel, leitplanken, auftrag_extra),
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
                      out.get("danger", ""))
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
                      out.get("verdict_reason") or "")
            break
        else:  # rejected (or unknown) → same builder retries with feedback
            rounds_done += 1
            prev_reason = out.get("verdict_reason") or ""
            accepted = False
    else:
        # max_rounds reached without saturation/escalation — clean stop.
        pass

    return _summary()
```

Plus der Feedback-Wrapper (kleiner Adapter, der `_relay_build_prompt` mit Feedback baut, statt es im Runner zu kennen) — vor `run_relay_loop`:

```python
def _relay_runner_with_feedback(runner, ziel, leitplanken, feedback):
    """Wrap a build runner so its `auftrag` is the relay build prompt (with the
    prior reject feedback). Keeps _relay_round agnostic of prompt construction."""
    prompt = _relay_build_prompt(ziel, leitplanken, feedback)
    def run(auftrag, fm, workroot):  # auftrag from _relay_round is ignored; we own it
        return runner(auftrag=prompt, fm=fm, workroot=workroot)
    return run
```

> **Hinweis für `_escalate`:** prüfe die echte Signatur von `_escalate` in
> `loop_driver.py` (goal-loop nutzt sie als `_escalate(loop_id, trigger,
> round_no, branch, commit, goal, done_criteria, reason)`). Übergib `ziel` als
> goal und `leitplanken` als die `done_criteria`-Position (sie landen nur als
> Kontext in der ESCALATION-Datei). Falls die Signatur abweicht, hier anpassen —
> NICHT `_escalate` ändern.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py -v`
Expected: alle PASS. Falls `_escalate`-Signatur abweicht, Step-3-Aufrufe anpassen und erneut laufen.

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): run_relay_loop (Rotation, Saettigung, Eskalation, max_rounds)"
```

---

## Task 7: CLI `--mode relay-loop`

**Files:**
- Modify: `scripts/loop_driver.py` (`main`, argparse + Mode-Zweig)
- Test: `scripts/test_relay_loop.py`

- [ ] **Step 1: Write the failing test**

```python
def test_cli_relay_loop_requires_repo(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    monkeypatch.setenv("DUAL_BRIDGE_STATE", str(tmp_path))
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    rc = loop_driver.main(["--mode", "relay-loop", "--max-rounds", "2",
                           "--seed", "## Ziel\nZ\n"])
    assert rc == 2  # missing --repo
    assert "repo" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_cli_relay_loop_requires_repo -v`
Expected: FAIL — argparse rejects `relay-loop` as an invalid `--mode` choice (SystemExit), not rc 2.

- [ ] **Step 3: Write minimal implementation**

(a) `--mode` choices erweitern:

```python
    parser.add_argument("--mode", default="ping-pong",
                        choices=["ping-pong", "build-review", "goal-loop", "relay-loop"],
                        help="ping-pong (Stage 1), build-review (Stage 2b), "
                             "goal-loop (Stage 3), or relay-loop (Stufe B: beide "
                             "bauen abwechselnd, Gegenmodell reviewt).")
```

(b) `--repo`-Pflichtcheck um `relay-loop` erweitern (bestehende Zeile mit `("build-review", "goal-loop")`):

```python
    if args.mode in ("build-review", "goal-loop", "relay-loop") and not args.repo:
        print(f"[A] --mode {args.mode} braucht --repo.")
        return 2
```

(c) Mode-Zweig nach dem `goal-loop`-Zweig (vor dem Fallback `run_loop`). `--adapter` ist der Startbuilder; relay erzwingt codex/claude-build:

```python
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
```

> `--reviewer` wird im relay-loop nicht ausgewertet (O1): das Gegenmodell ist
> konstitutiv. Der bestehende `--reviewer`-Help-Text aus Stufe A erwähnt nur
> build-review/goal-loop — unverändert lassen.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python -X utf8 -m pytest test_relay_loop.py::test_cli_relay_loop_requires_repo -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_relay_loop.py
git commit -m "feat(relay): CLI --mode relay-loop"
```

---

## Task 8: Voll-Suite, Doku, Real-Binary-Live-Proof

**Files:**
- Modify: `README.md`, `HOW-TO-USE.md`, `CLAUDE.md` (relay-loop in der Modi-Liste + Soll-Testzahl)
- Create: `docs/live-proofs/stageB-relay-loop.md`

- [ ] **Step 1: Voll-Suite grün**

Run: `cd scripts && python -X utf8 -m pytest -q -p no:cacheprovider`
Expected: PASS, neue Soll-Zahl = 441 + Anzahl neuer relay-Tests. Notiere die Zahl.

- [ ] **Step 2: Soll-Testzahl + Modi-Liste nachziehen**

In `README.md` und `HOW-TO-USE.md` die „441 Tests grün"-Stellen auf die neue Zahl setzen. In `CLAUDE.md` unter „Goal-Loop (Stufe 3)"/Modi den `relay-loop` ergänzen: „`relay-loop` (Stufe B): beide bauen abwechselnd (codex↔claude-build), Gegenmodell reviewt, offenes Ziel + Leitplanken, Ende bei Sättigung/Eskalation/max_rounds."

- [ ] **Step 3: Real-Binary-Live-Proof (manuell, beide Binaries nötig)**

Gegen ein Wegwerf-Repo einen kurzen Relay fahren (2–3 Schritte). codex + claude müssen lokal verfügbar sein:

```bash
cd scripts && python -X utf8 loop_driver.py --mode relay-loop \
  --repo <wegwerf-repo-url> --adapter codex --max-rounds 3 \
  --round-timeout 600 --seed docs/live-proofs/relay-seed.md
```

Beweisen: (1) Runde 0 baut codex, Reviewer = claude; (2) nach accept baut Runde 1 claude-build, Reviewer = codex-review (kein Hang, §10.10); (3) sauberer Stop bei Sättigung ODER max_rounds. Branch `bridge/<loop_id>` auf GitHub ground-truth prüfen.

- [ ] **Step 4: Live-Proof dokumentieren**

`docs/live-proofs/stageB-relay-loop.md` anlegen: Datum, codex/claude-Versionen, beobachtete Rotation (Builder/Reviewer je Runde), Dauer, Verdikte, Endgrund, Branch-Commit-Kette als Ground-Truth. Format analog `docs/live-proofs/stageA-codex-review-symmetry.md`.

- [ ] **Step 5: Commit**

```bash
git add README.md HOW-TO-USE.md CLAUDE.md docs/live-proofs/stageB-relay-loop.md
git commit -m "docs(relay): Modi-Liste + Soll-Testzahl + Stufe-B-Live-Proof"
```

---

## Self-Review-Ergebnis (vom Plan-Autor)

- **Spec-Coverage:** D1 Gate → Task 4/5 (Review-Schritt). D2 Ende → Task 6 (saturation/escalate/dangerous/max_rounds). D3 Seed → Task 2. D4 eigener Modus → Task 6/7. D5 Rotation bei accept → Task 6 (+ Test). D6 Inkrement-Diff → Task 1 + Task 5 (`_relay_increment_diff`). D7 Sättigung zweigleisig → Task 5 (leerer Diff) + Task 4/6 (escalate-Sättigung). D8 Startbuilder → Task 7. O1 → Task 7 (ignoriert). O2 → Task 1 + Task 5 (Fallback + Test).
- **Platzhalter:** keine — jeder Code-Step enthält vollständigen Code; `_escalate`-Signatur ist als „gegen echten Code prüfen"-Hinweis markiert (kein erfundener Aufruf, sondern explizite Verifikationsanweisung, da die Funktion bereits existiert).
- **Typ-Konsistenz:** `_relay_round` liefert ein Dict mit `builder`/`reviewer`/`verdict`/`commit`/`saturated`/`status`; `run_relay_loop` liest exakt diese Schlüssel. `build_runner_for(adapter)→runner(auftrag,fm,workroot)→RunnerResult` durchgängig. `_other_builder`/`_reviewer_adapter`/`parse_relay_seed`-Signaturen stimmen zwischen Definition und Aufruf.
