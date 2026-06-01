# A↔B Ping-Pong-Loop — Stufe 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Einen selbst-treibenden A↔B-Loop bauen, der pro Runde echte Arbeit abwechselnd auf A und B ausführt (Counter-Demo), zentral von A getrieben, mit `--max-rounds N` und Per-Runde-Timeout.

**Architecture:** Neuer `loop_driver.py` auf A nutzt die bestehenden Bridge-Bausteine als Bibliothek. B bleibt der unveränderte `handoff_poll.py --watch`-Worker. Ein generischer Umschlag (`loop_id`/`round`/`payload`) wird über den bestehenden MIRROR_FIELDS-Mechanismus durch Task→Result gereicht; die `increment`-Runner-Logik läuft auf beiden Knoten gleich.

**Tech Stack:** Python 3 (pure stdlib, keine Third-Party-Deps), pytest mit dem bestehenden `scripts/conftest.py` (Env-Snapshot + Runner-Re-Register für Isolation).

**Spec:** `docs/superpowers/specs/2026-06-02-dual-bridge-pingpong-loop-design.md`

---

## Wichtige bestehende Signaturen (NICHT erfinden — so heißen sie wirklich)

Aus `bridge_common.py` (`import bridge_common as bc`):
- `bc.make_task_id() -> str`, `bc.is_valid_task_id(s) -> bool`
- `bc.now_iso() -> str`
- `bc.parse_frontmatter(text) -> tuple[dict, str]`, `bc.build_document(fm: dict, body: str) -> str`
- `bc.read_text_utf8(path) -> str`, `bc.write_text_utf8(path, content)`, `bc.write_text_atomic(path, content)`
- `bc.lane_outbox(lane) -> Path`, `bc.lane_inbox(lane) -> Path`, `bc.lane_processed(lane) -> Path`
- `bc.send_lane() -> str`, `bc.receive_lanes() -> list[str]`, `bc.this_endpoint() -> str`
- `bc.ensure_dirs()`, `bc.DEVICE`
- `bc.acquire_singleton_lock(lock_path=None) -> bool`, `bc.release_singleton_lock(lock_path=None)`, `bc.default_lock_path() -> Path`

Aus `runners.py` (`import runners`):
- `runners.RunnerResult(status, antwort="", branch=None, commit=None, changed_files=[], error_text=None, stderr_excerpt=None, note=None, verdict=None, verdict_reason=None)`
- `runners.RUNNERS: dict[str, Callable]`, `runners.register_runner(name, fn)`
- Runner-Vertrag: `fn(auftrag: str, fm: dict, workroot: Path|None) -> RunnerResult`

Aus `handoff_poll.py` (`import handoff_poll`):
- Modul-Konstante `MIRROR_FIELDS = ("gate_id", "run_id", "stage")` — wird in `_build_result_fm` verbatim vom Task-FM ins Result-FM gespiegelt.
- `handoff_poll.poll_once() -> int` (für den Test-B-Worker im selben tmp).

---

## File Structure

- **Create** `scripts/loop_driver.py` — der A-seitige Loop-Treiber (Schleife, Rundenzählung, A-Runner inline, Task schreiben, auf Result warten mit Timeout, State-jsonl, Final-Summary). Eine klare Verantwortung.
- **Modify** `scripts/runners.py` — neuer `increment`-Runner + Registrierung.
- **Modify** `scripts/handoff_poll.py` — `MIRROR_FIELDS` um den Loop-Umschlag erweitern, damit `loop_id`/`round`/`payload` durch das Result-FM gespiegelt werden.
- **Modify** `scripts/handoff_write.py` — `increment` zu den `--adapter`-`choices` ergänzen (damit auch CLI-Tasks den Runner wählen können; der Treiber schreibt FM direkt, braucht es nicht, aber Konsistenz).
- **Create** `scripts/test_loop_driver.py` — alle 6 Tests aus der Spec.

Loop-State-Datei (gitignored, kein Code): `scripts/state/LOOP-<loop_id>.jsonl`.

---

## Task 1: `increment`-Runner

**Files:**
- Modify: `scripts/runners.py`
- Test: `scripts/test_loop_driver.py`

- [ ] **Step 1: Failing-Test schreiben**

Neue Datei `scripts/test_loop_driver.py` anlegen mit:

```python
"""Stage-1 ping-pong loop tests. Isoliert, kein echtes Drive (conftest.py setzt
DUAL_BRIDGE_ROOT auf tmp + re-registriert Runner)."""
from __future__ import annotations

from pathlib import Path

import bridge_common as bc
import runners


def test_increment_runner_adds_one():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="3", fm={"payload": "3"}, workroot=None)
    assert res.status == "done"
    assert res.antwort.strip() == "4"


def test_increment_runner_rejects_non_numeric():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="abc", fm={"payload": "abc"}, workroot=None)
    assert res.status == "error"
    assert res.error_text  # nicht-leer, kein stiller Default
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_increment_runner_adds_one -v`
Expected: FAIL mit `KeyError: 'increment'`.

- [ ] **Step 3: Runner implementieren**

In `scripts/runners.py` nach `run_echo` einfügen:

```python
def run_increment(auftrag: str, fm: dict, workroot: Path | None) -> RunnerResult:
    """Stage-1 loop work: read the loop payload as an int and return +1.

    The payload travels in fm['payload'] (the loop envelope). Falls back to
    `auftrag` when fm has no payload (e.g. a plain CLI task). A non-numeric
    payload is a hard error — never a silent default."""
    raw = fm.get("payload", auftrag)
    try:
        nxt = int(str(raw).strip()) + 1
    except (TypeError, ValueError):
        return RunnerResult(
            status="error",
            error_text=f"increment: payload {raw!r} ist keine ganze Zahl",
        )
    return RunnerResult(status="done", antwort=str(nxt))
```

Und am Ende der Datei (nach `register_runner`-Definition) registrieren:

```python
register_runner("increment", run_increment)
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k increment -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/runners.py scripts/test_loop_driver.py
git commit -m "feat(loop): add increment runner for ping-pong stage 1"
```

---

## Task 2: Loop-Umschlag durch MIRROR_FIELDS spiegeln

**Files:**
- Modify: `scripts/handoff_poll.py:31` (die `MIRROR_FIELDS`-Konstante)
- Test: `scripts/test_loop_driver.py`

Begründung: `_build_result_fm` spiegelt jedes Feld aus `MIRROR_FIELDS` verbatim vom Task-FM ins Result-FM (absent-safe — leere Werte werden NICHT injiziert). Wenn `loop_id`/`round`/`payload` dort stehen, reicht B sie automatisch zurück. ABER: der `payload` im Result muss der NEU berechnete sein (Runner-Output), nicht der Eingangs-payload. Deshalb spiegeln wir `loop_id`/`round` über MIRROR_FIELDS, und den `payload` setzt der Poller aus dem Runner-Ergebnis (Task 3).

- [ ] **Step 1: Failing-Test schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def _write_task(lane: str, fm_extra: dict, body_auftrag: str) -> str:
    """Helper: write an open task into lane outbox, return task_id."""
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "schema_version": "2",
        "agent": "claude@laptop-a", "from": "claude@laptop-a",
        "to": "codex@laptop-b", "purpose": "handoff", "status": "open",
        "task_id": task_id, "kind": "echo", "adapter": "increment",
        "claimed_by": "", "claimed_at": "",
    }
    fm.update(fm_extra)
    body = f"## Auftrag\n{body_auftrag}\n\n## Ergebnis\n<offen>\n"
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def test_loop_id_and_round_are_mirrored(monkeypatch):
    """loop_id + round müssen vom Task-FM ins Result-FM gespiegelt werden."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)  # re-resolve endpoint
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"loop_id": "loop-xyz", "round": "2",
                                 "payload": "5"}, "5")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    assert result.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert fm.get("loop_id") == "loop-xyz"
    assert fm.get("round") == "2"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_loop_id_and_round_are_mirrored -v`
Expected: FAIL — `fm.get("loop_id")` ist `None` (noch nicht gespiegelt).

- [ ] **Step 3: MIRROR_FIELDS erweitern**

In `scripts/handoff_poll.py`, Zeile 31, ändern:

```python
MIRROR_FIELDS = ("gate_id", "run_id", "stage", "loop_id", "round")
```

(Bewusst OHNE `payload` — der wird in Task 3 aus dem Runner-Output gesetzt, nicht vom Eingang gespiegelt.)

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_loop_id_and_round_are_mirrored -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/handoff_poll.py scripts/test_loop_driver.py
git commit -m "feat(loop): mirror loop_id+round through result frontmatter"
```

---

## Task 3: Poller setzt den neuen `payload` aus dem Runner-Output

**Files:**
- Modify: `scripts/handoff_poll.py` (`_build_result_fm`, ~Zeile 67-97)
- Test: `scripts/test_loop_driver.py`

Begründung: Der Loop braucht im Result-FM einen `payload` = der vom Runner berechnete nächste Wert. Der Runner liefert ihn in `result.antwort` (increment gibt die Zahl als `antwort`). Wir setzen `payload` im Result-FM NUR, wenn der eingehende Task ein `loop_id` trägt (also Teil eines Loops ist) — sonst bleibt der normale Bridge-Pfad unberührt.

- [ ] **Step 1: Failing-Test schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def test_loop_payload_is_runner_output(monkeypatch):
    """Result-FM payload muss der vom increment-Runner berechnete Wert sein."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"loop_id": "loop-pay", "round": "0",
                                 "payload": "5"}, "5")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert fm.get("payload") == "6"   # 5 + 1


def test_non_loop_task_has_no_payload(monkeypatch):
    """Ein Task ohne loop_id bekommt KEIN payload-Feld ins Result (Bridge unberührt)."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "codex@laptop-b")
    import importlib
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    lane = "A-to-B"
    task_id = _write_task(lane, {"adapter": "echo"}, "hallo")
    handoff_poll.poll_once()
    result = bc.lane_inbox(lane) / f"result-{task_id}.md"
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert "payload" not in fm
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_loop_payload_is_runner_output -v`
Expected: FAIL — `payload` fehlt im Result-FM.

- [ ] **Step 3: `_build_result_fm` erweitern**

In `scripts/handoff_poll.py`, in `_build_result_fm`, NACH der `MIRROR_FIELDS`-Schleife (vor `return result_fm`) einfügen:

```python
    # Loop envelope: a task that carries loop_id is part of a ping-pong loop.
    # Its result payload is the RUNNER OUTPUT (the next value), not the echoed
    # input. Only set when the task is a loop task AND the runner succeeded.
    if fm.get("loop_id") and result.status == "done":
        result_fm["payload"] = result.antwort.strip()
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k "payload" -v`
Expected: 2 PASS (`test_loop_payload_is_runner_output`, `test_non_loop_task_has_no_payload`).

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/handoff_poll.py scripts/test_loop_driver.py
git commit -m "feat(loop): set result payload from runner output for loop tasks"
```

---

## Task 4: `loop_driver.py` — Gerüst, ein Runde-Schreibschritt

**Files:**
- Create: `scripts/loop_driver.py`
- Test: `scripts/test_loop_driver.py`

- [ ] **Step 1: Failing-Test schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def test_driver_writes_loop_task(monkeypatch):
    """write_round_task schreibt einen Task mit korrektem Loop-Umschlag."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    task_id = loop_driver.write_round_task(
        loop_id="loop-w", round_no=0, payload="7", adapter="increment")
    lane = bc.send_lane()  # A-to-B
    task = bc.lane_outbox(lane) / f"task-{task_id}.md"
    assert task.exists()
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(task))
    assert fm["loop_id"] == "loop-w"
    assert fm["round"] == "0"
    assert fm["payload"] == "7"
    assert fm["adapter"] == "increment"
    assert fm["status"] == "open"
```

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_driver_writes_loop_task -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'loop_driver'`.

- [ ] **Step 3: `loop_driver.py` mit `write_round_task` anlegen**

```python
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
            "## Ergebnis\n<wird vom Empfänger gefüllt>\n")
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_driver_writes_loop_task -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_loop_driver.py
git commit -m "feat(loop): loop_driver write_round_task skeleton"
```

---

## Task 5: `wait_for_result` mit Timeout

**Files:**
- Modify: `scripts/loop_driver.py`
- Test: `scripts/test_loop_driver.py`

- [ ] **Step 1: Failing-Tests schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def _write_result(lane: str, task_id: str, fm_extra: dict, status="done"):
    fm = {"created": bc.now_iso(), "agent": "codex@laptop-b",
          "from": "codex@laptop-b", "to": "claude@laptop-a",
          "purpose": "handoff", "status": status, "task_id": task_id,
          "kind": "echo", "adapter": "increment",
          "replies_to": f"task-{task_id}.md"}
    fm.update(fm_extra)
    bc.write_text_utf8(bc.lane_inbox(lane) / f"result-{task_id}.md",
                       bc.build_document(fm, "## Antwort\nok\n"))


def test_wait_for_result_returns_fm(monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    lane = bc.receive_lanes()[0]  # B-to-A
    tid = bc.make_task_id()
    _write_result(lane, tid, {"payload": "9"})
    fm = loop_driver.wait_for_result(tid, timeout=5, interval=1)
    assert fm is not None
    assert fm["payload"] == "9"


def test_wait_for_result_times_out(monkeypatch):
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    bc.ensure_dirs()
    fm = loop_driver.wait_for_result("20260101-000000-000000-0-aaaa",
                                     timeout=2, interval=1)
    assert fm is None
```

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k wait_for_result -v`
Expected: FAIL — `AttributeError: module 'loop_driver' has no attribute 'wait_for_result'`.

- [ ] **Step 3: `wait_for_result` implementieren**

In `scripts/loop_driver.py` nach `write_round_task` einfügen:

```python
def _is_conflict_copy(name: str) -> bool:
    return "(" in name and ")" in name


def wait_for_result(task_id: str, timeout: int, interval: int = 5):
    """Poll THIS endpoint's receive-lane inbox for result-<task_id>.md until it
    appears or `timeout` seconds elapse. Returns the result frontmatter dict, or
    None on timeout. Drive conflict copies ('(1)') are ignored. Archives the
    consumed result into _processed/ so it is not re-read next round."""
    lane = bc.receive_lanes()[0]
    target_name = f"result-{task_id}.md"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = bc.lane_inbox(lane) / target_name
        if path.exists() and not _is_conflict_copy(path.name):
            fm, _ = bc.parse_frontmatter(bc.read_text_utf8(path))
            try:
                (bc.lane_processed(lane) / target_name).unlink(missing_ok=True)
                path.replace(bc.lane_processed(lane) / target_name)
            except OSError:
                pass  # best-effort archive; we already have the fm
            return fm
        time.sleep(interval)
    return None
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k wait_for_result -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_loop_driver.py
git commit -m "feat(loop): wait_for_result with per-round timeout"
```

---

## Task 6: State-jsonl-Schreiber

**Files:**
- Modify: `scripts/loop_driver.py`
- Test: `scripts/test_loop_driver.py`

- [ ] **Step 1: Failing-Test schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def test_append_state_writes_jsonl(tmp_path, monkeypatch):
    import importlib
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    loop_driver.append_state("loop-s", {"round": 0, "side": "B",
                                        "payload_in": "1", "payload_out": "2",
                                        "task_id": "t", "status": "done"})
    f = tmp_path / "LOOP-loop-s.jsonl"
    assert f.exists()
    line = json.loads(f.read_text(encoding="utf-8").strip())
    assert line["round"] == 0 and line["payload_out"] == "2"
    assert "ts" in line  # Zeitstempel wird ergänzt
```

(Am Kopf der Testdatei `import json` ergänzen, falls noch nicht da.)

- [ ] **Step 2: Test laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_append_state_writes_jsonl -v`
Expected: FAIL — `AttributeError: ... 'append_state'`.

- [ ] **Step 3: `append_state` implementieren**

In `scripts/loop_driver.py` nach `wait_for_result` einfügen:

```python
def append_state(loop_id: str, record: dict) -> None:
    """Append one round record to scripts/state/LOOP-<loop_id>.jsonl (history,
    A-side only). Adds an ISO timestamp. Append-only, never deletes."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = dict(record, ts=bc.now_iso())
    path = STATE_DIR / f"LOOP-{loop_id}.jsonl"
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
```

- [ ] **Step 4: Test laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py::test_append_state_writes_jsonl -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_loop_driver.py
git commit -m "feat(loop): append-only loop state history jsonl"
```

---

## Task 7: Die Loop-Schleife `run_loop` (max-rounds, A-Arbeit inline, Abbruch)

**Files:**
- Modify: `scripts/loop_driver.py`
- Test: `scripts/test_loop_driver.py`

Das ist der Kern: A arbeitet inline, schreibt Task, wartet, liest B's payload, nächste Runde. Test fährt einen echten B-Poll im selben tmp zwischen den Runden (über einen injizierten "B-Tick").

- [ ] **Step 1: Failing-Tests schreiben**

In `scripts/test_loop_driver.py` ergänzen:

```python
def _run_b_tick():
    """Simuliert B: ein Poll-Durchlauf, verarbeitet offene A->B-Tasks.
    Läuft als B-Endpoint, danach Endpoint zurück auf A."""
    import importlib, os
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "codex@laptop-b"
    importlib.reload(bc)
    import handoff_poll
    importlib.reload(handoff_poll)
    handoff_poll.poll_once()
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
    importlib.reload(bc)


def test_run_loop_max_rounds(tmp_path, monkeypatch):
    """3 Runden: A+B inkrementieren je Runde -> payload = seed + 2*rounds.
    jsonl hat genau `rounds` Zeilen."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=5, interval=1, b_tick=_run_b_tick)
    assert summary["rounds_done"] == 3
    assert summary["final_payload"] == "6"   # 0 + 2*3
    assert summary["aborted"] is False
    jsonl = tmp_path / f"LOOP-{summary['loop_id']}.jsonl"
    assert len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_run_loop_aborts_on_timeout(tmp_path, monkeypatch):
    """Kein B-Tick -> B-Result kommt nie -> sauberer Abbruch nach Timeout."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)
    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=2, interval=1, b_tick=lambda: None)
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 0
    assert summary["open_task_id"]  # offener Task wird gemeldet


def test_run_loop_aborts_on_b_error(tmp_path, monkeypatch):
    """B liefert status:error -> fail-fast Abbruch, payload nicht verschleppt."""
    monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")
    import importlib
    importlib.reload(bc)
    import loop_driver
    importlib.reload(loop_driver)
    monkeypatch.setattr(loop_driver, "STATE_DIR", tmp_path)

    def _b_error_tick():
        """B claimt den offenen A->B-Task und schreibt ein error-Result."""
        send = "A-to-B"
        for task in bc.lane_outbox(send).glob("task-*.md"):
            if ".claimed-" in task.name:
                continue
            fm, _ = bc.parse_frontmatter(bc.read_text_utf8(task))
            tid = fm["task_id"]
            recv_lane = bc.receive_lanes()[0]  # B-to-A (A's inbox)
            _write_result(recv_lane, tid, {"loop_id": fm.get("loop_id", "")},
                          status="error")

    summary = loop_driver.run_loop(
        seed="0", max_rounds=3, adapter="increment",
        round_timeout=5, interval=1, b_tick=_b_error_tick)
    assert summary["aborted"] is True
    assert summary["rounds_done"] == 0
    assert "error" in summary["abort_reason"].lower()
```

Hinweis: `_b_error_tick` schreibt das error-Result in A's Empfangs-Lane (`B-to-A`), damit
`wait_for_result` es sieht. `_write_result` (aus Task 5) wird wiederverwendet.

- [ ] **Step 2: Tests laufen lassen, Fehlschlag verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k run_loop -v`
Expected: FAIL — `AttributeError: ... 'run_loop'`.

- [ ] **Step 3: `run_loop` implementieren**

In `scripts/loop_driver.py` nach `append_state` einfügen:

```python
def _next_loop_id() -> str:
    return f"loop-{bc.make_task_id()}"


def run_loop(seed: str, max_rounds: int, adapter: str, round_timeout: int,
             interval: int = 5, b_tick=None) -> dict:
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
        # 1. A works inline on the current payload.
        runner = runners.RUNNERS.get(adapter)
        if runner is None:
            aborted, abort_reason = True, f"unbekannter adapter {adapter!r}"
            break
        try:
            a_res = runner(auftrag=payload, fm={"payload": payload},
                           workroot=None)
        except Exception as exc:  # noqa: BLE001
            aborted, abort_reason = True, f"A-runner crash: {exc}"
            break
        if a_res.status != "done":
            aborted, abort_reason = True, f"A-runner error: {a_res.error_text}"
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
```

- [ ] **Step 4: Tests laufen lassen, Erfolg verifizieren**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest test_loop_driver.py -k run_loop -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/test_loop_driver.py
git commit -m "feat(loop): run_loop with max-rounds + fail-safe abort"
```

---

## Task 8: CLI `main` + Singleton-Lock + `increment` in handoff_write choices

**Files:**
- Modify: `scripts/loop_driver.py` (CLI)
- Modify: `scripts/handoff_write.py:42-44` (`--adapter` choices)

- [ ] **Step 1: `increment` zu handoff_write choices ergänzen**

In `scripts/handoff_write.py`, im `--adapter`-Argument:

```python
    parser.add_argument("--adapter", default="echo",
                        choices=["echo", "codex", "claude", "increment"],
                        help="Which runner the receiver should use.")
```

- [ ] **Step 2: CLI-`main` in loop_driver.py ergänzen**

Am Ende von `scripts/loop_driver.py`:

```python
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
    parser.add_argument("--interval", type=int, default=5,
                        help="Poll interval while waiting for a result.")
    args = parser.parse_args(argv)

    # Singleton: one loop driver per machine (reuses the poller lock pattern,
    # local lock file, never the Drive root). Uses a loop-specific lock name.
    lock = bc.default_lock_path().with_name("dual-bridge-loop.lock")
    if not bc.acquire_singleton_lock(lock):
        print("[A] Ein Loop-Treiber läuft bereits — ich beende mich.")
        return 0

    print(f"[A] Bridge-Root: {bc.bridge_root()}")
    print(f"[A] Loop: seed={args.seed} max_rounds={args.max_rounds} "
          f"adapter={args.adapter} round_timeout={args.round_timeout}s")
    try:
        summary = run_loop(seed=args.seed, max_rounds=args.max_rounds,
                           adapter=args.adapter,
                           round_timeout=args.round_timeout,
                           interval=args.interval, b_tick=None)
    except KeyboardInterrupt:
        print("\n[A] Strg+C — Loop abgebrochen.")
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
```

- [ ] **Step 3: Smoke der CLI-Hilfe (kein echtes Drive)**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python loop_driver.py --help`
Expected: Usage-Text mit `--seed`, `--max-rounds`, `--round-timeout` — kein Traceback.

- [ ] **Step 4: Volle Test-Suite laufen lassen (Regression)**

Run: `cd C:/Users/domes/AI/dual-bridge/scripts && python -m pytest -v`
Expected: bestehende 56 grün + neue Loop-Tests grün. Keine Regression.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/domes/AI/dual-bridge
git add scripts/loop_driver.py scripts/handoff_write.py
git commit -m "feat(loop): loop_driver CLI + singleton lock + increment in write choices"
```

---

## Task 9: Live-Beweis über die echte Bridge (manuell, Ground-Truth)

**Files:** keine (Betrieb + Verifikation)

Dieser Task ist KEIN automatisierter Test — er beweist den Loop über das echte Drive,
mit B als separatem Live-Poller. Pflicht laut Spec (P006/P007: echtes Binary, Output real
gegenlesen, nicht nur Exit-Code).

- [ ] **Step 1: Auf Laptop B den Worker starten**

Auf B (PowerShell):
```powershell
$env:DUAL_BRIDGE_ENDPOINT="codex@laptop-b"
cd ~/AI/dual-bridge/scripts
python handoff_poll.py --watch --interval 10
```
Erwartet: `[B] Watch-Modus, alle 10s.`

- [ ] **Step 2: Auf Laptop A den Loop starten (3 Runden)**

Auf A:
```bash
cd C:/Users/domes/AI/dual-bridge/scripts
python loop_driver.py --seed 0 --max-rounds 3 --adapter increment --round-timeout 300 --interval 10
```
Erwartet: nach ~3 Roundtrips (Drive-Latenz ~180s/Runde möglich) `Runden: 3/3`, `Final-Payload: 6`, `aborted=False`.

- [ ] **Step 3: Ground-Truth gegenlesen (NICHT nur Exit-Code glauben — P007)**

Run: `cat C:/Users/domes/AI/dual-bridge/scripts/state/LOOP-*.jsonl`
Prüfen: genau 3 Zeilen, `round` 0/1/2, `payload_out` 2/4/6, jede `status:done`,
`side:B`, plausible `ts`. Die Zahlen real ansehen, nicht nur zählen.

- [ ] **Step 4: Loop-Tasks in den Lanes prüfen (Provenance)**

Run: `ls "G:/Meine Ablage/dynamic-AI/dynamic_sharepoint/00_INBOX/dual-bridge/lane-A-to-B/_processed/"`
Erwartet: 3 verarbeitete `task-*.claimed-*` der Runde. Kein offener Rest in `outbox/`.

- [ ] **Step 5: Befund festhalten**

Ergebnis (Runden, Final-Payload, Latenz/Runde, Auffälligkeiten) für die Session-Summary
notieren. Bei Abweichung (Timeout, payload-Drift) NICHT als Erfolg melden — Bug aufnehmen.

---

## Notes für den ausführenden Worker

- **Test-Isolation (Pflicht, globale Regel 3) — UPDATE 2026-06-02:** `scripts/conftest.py`
  wurde gehärtet (Commit `ff70df3`): die autouse-Fixture setzt `DUAL_BRIDGE_ROOT` jetzt
  ZWANGSWEISE auf ein frisches per-Test-tmp (`tmp_path_factory`) und hat einen Poison-Guard
  (RuntimeError, falls der Root je `dynamic_sharepoint` enthält, vor + nach jedem Test).
  Grund: vorher setzte conftest das Root NICHT → ein Test ohne eigenen Override schrieb ins
  echte Google Drive (Vorfall behoben, [[wiki/todos/2026-06-02-dual-bridge-test-drive-leak]]).
  Konsequenz für diese Tasks: Tests müssen `DUAL_BRIDGE_ROOT` NICHT mehr selbst setzen — die
  conftest erledigt es. `STATE_DIR` wird weiterhin per `monkeypatch.setattr(loop_driver,
  "STATE_DIR", tmp_path)` isoliert (Tasks 6/7). Niemals gegen das echte Drive testen.
- **Reload-Muster:** Mehrere Tests reloaden `bc`/`handoff_poll`/`loop_driver` nach
  `DUAL_BRIDGE_ENDPOINT`-Wechsel, weil `this_endpoint()`/`send_lane()` beim Import aufgelöst
  werden. Das `conftest.py` re-registriert Runner nach reload (sonst Runner-Registry-Leak,
  Pattern P011 aus der Vorsession).
- **Windows:** Pfade in Tests über `tmp_path`/`Path`, keine Shell-Quoting-Fallen. `python -m pytest`
  aus `scripts/` ausführen (dort liegt `conftest.py`).
- **Frequent commits:** ein Commit pro Task (Red→Green→Commit). Chirurgisch stagen (Regel 7),
  kein `git add -A`.
