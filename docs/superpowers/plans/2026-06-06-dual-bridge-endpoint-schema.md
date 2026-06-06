# Endpoint-Schema (Hostname-Auto-Erkennung) + Stale-PID-Liveness-Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `this_endpoint()` leitet die Bridge-Identität override-zuerst aus dem Hostname ab (statt hart `claude@laptop-a`), und `_pid_alive()` erkennt recycelte PIDs per Cmdline-Match, sodass der Singleton-Lock keinen Stale-PID-False-Positive mehr produziert.

**Architecture:** Beide Fixes sitzen in `scripts/bridge_common.py`. Teil 1 ergänzt eine `HOSTNAME_TO_ENDPOINT`-Tabelle + dreistufige Auflösung (Override → Hostname → klarer Fehler). Teil 2 erweitert `_pid_alive()` um einen optionalen Cmdline-Marker-Check (fail-safe konservativ). Die conftest-Fixture zwingt den Endpoint pro Test auf einen Default, damit die Suite unabhängig vom `setx` der Maschine läuft.

**Tech Stack:** Python 3.12 (stdlib: `socket`, `subprocess`), pytest, Windows-`Get-CimInstance` für Cmdline-Abfrage.

---

## Wichtige Vorbedingungen (jeder Worker liest das zuerst)

- **Test-Befehl IMMER mit Default-Endpoint** (sonst greift dein Maschinen-`setx`):
  `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest -q`
  Nach Task 5 ist das nicht mehr nötig (conftest zwingt den Default), aber bis dahin Pflicht.
- **Test-DB-Isolation:** `scripts/conftest.py` hat eine autouse-Fixture, die `DUAL_BRIDGE_ROOT`/`DUAL_BRIDGE_LOCK` auf `tmp_path_factory` lenkt + Poison-Guard gegen den echten Drive. NICHT umgehen.
- **Code-Anker** (`scripts/bridge_common.py`): `ENDPOINTS` (~Z133), `this_endpoint` (~Z140), `_endpoint_cfg`/`receive_lanes`/`send_lane` (~Z170-190), `_pid_alive` (~Z438), `_subprocess_run_quiet` (~Z456), `acquire_singleton_lock` (~Z477).
- **Windows-Subprocess-Härtung (globale Regel §10):** `Get-CimInstance` via `powershell -ExecutionPolicy Bypass -Command`; stdin=DEVNULL; Decode-Fehler abfangen.

## File Structure

- **Modify** `scripts/bridge_common.py` — Teil 1 (Endpoint-Auflösung) + Teil 2 (Liveness).
- **Modify** `scripts/conftest.py` — Endpoint-Default in der Isolations-Fixture.
- **Create** `scripts/test_endpoint_resolution.py` — Tests Teil 1.
- **Create** `scripts/test_pid_liveness.py` — Tests Teil 2.
- **Modify** `README.md` + `CLAUDE.md` — Doku/Migrationsnotiz.

---

## Task 1: Hostname-Auto-Erkennung in `this_endpoint()`

**Files:**
- Modify: `scripts/bridge_common.py` (`this_endpoint`, ~Z140; neue Konstante nach `ENDPOINTS`)
- Test: `scripts/test_endpoint_resolution.py` (neu)

- [ ] **Step 1: Failing-Test schreiben**

Datei `scripts/test_endpoint_resolution.py`:

```python
"""Tests for hostname-based endpoint resolution (override -> hostname -> error)."""
from __future__ import annotations

import importlib
import pytest


def _fresh(monkeypatch, *, endpoint=None, hostname=None):
    """Reload bridge_common with a controlled env + hostname, return the module."""
    import bridge_common as bc
    if endpoint is None:
        monkeypatch.delenv("DUAL_BRIDGE_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("DUAL_BRIDGE_ENDPOINT", endpoint)
    importlib.reload(bc)
    if hostname is not None:
        monkeypatch.setattr(bc.socket, "gethostname", lambda: hostname)
    return bc


def test_override_wins_over_hostname(monkeypatch):
    bc = _fresh(monkeypatch, endpoint="codex@laptop-b", hostname="K472HEXXZACKBUU")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_dome_dynamics_maps_to_laptop_b(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="DOME-DYNAMICS")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_is_case_insensitive(monkeypatch):
    # gethostname() really returns "DoMe-Dynamics" (mixed case) on this machine.
    bc = _fresh(monkeypatch, endpoint=None, hostname="DoMe-Dynamics")
    assert bc.this_endpoint() == "codex@laptop-b"


def test_hostname_k472_maps_to_laptop_a(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="K472HEXXZACKBUU")
    assert bc.this_endpoint() == "claude@laptop-a"


def test_unknown_host_without_override_raises(monkeypatch):
    bc = _fresh(monkeypatch, endpoint=None, hostname="SOME-RANDOM-PC")
    with pytest.raises(ValueError) as exc:
        bc.this_endpoint()
    msg = str(exc.value)
    assert "SOME-RANDOM-PC" in msg          # names the detected host
    assert "DUAL_BRIDGE_ENDPOINT" in msg    # tells the user how to fix it
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_endpoint_resolution.py -q`
Expected: FAIL — `this_endpoint()` ignoriert hostname noch (gibt den Default zurück / kein ValueError). `bc.socket` existiert evtl. noch nicht → ggf. AttributeError, auch ein gültiger RED.

- [ ] **Step 3: Implementierung**

In `scripts/bridge_common.py` sicherstellen, dass `socket` importiert ist (oben bei den Imports; falls nicht vorhanden, `import socket` ergänzen).

Direkt nach dem `ENDPOINTS`-Dict + `DEFAULT_LANE` (vor `this_endpoint`) einfügen:

```python
# Hostname -> full endpoint string. The endpoint encodes the MACHINE (a/b), which
# is all that determines lane direction; the claude@/codex@ prefix is cosmetic
# (the real adapter comes from the task's `adapter:` field). Auto-detecting from
# the hostname removes the recurring role/agent confusion and the hard
# claude@laptop-a default that made the suite depend on a machine's setx value.
# NOTE: gethostname() returns mixed case ("DoMe-Dynamics") while the Drive claims
# carry "DOME-DYNAMICS" -> match case-insensitively.
HOSTNAME_TO_ENDPOINT = {
    "DOME-DYNAMICS":   "codex@laptop-b",
    "K472HEXXZACKBUU": "claude@laptop-a",
}
```

`this_endpoint()` ersetzen:

```python
def this_endpoint() -> str:
    """Who am I. Resolution order: explicit DUAL_BRIDGE_ENDPOINT override ->
    hostname auto-detection (case-insensitive) -> ValueError naming the host.
    No silent claude@laptop-a fallback: an unknown host must be configured, not
    guessed (the wrong-default drift cost real diagnosis time, Wiki-TODO P2)."""
    override = os.environ.get("DUAL_BRIDGE_ENDPOINT")
    if override:
        return override
    host = socket.gethostname()
    mapped = HOSTNAME_TO_ENDPOINT.get(host.upper())
    if mapped:
        return mapped
    raise ValueError(
        f"Unbekannter Host {host!r} und kein DUAL_BRIDGE_ENDPOINT gesetzt. "
        f"Bekannte Hosts: {', '.join(HOSTNAME_TO_ENDPOINT)}. "
        f"Setze die Identitaet explizit, z.B.: "
        f"setx DUAL_BRIDGE_ENDPOINT \"codex@laptop-b\""
    )
```

Die `HOSTNAME_TO_ENDPOINT`-Keys sind bereits uppercase → `host.upper()` matcht case-insensitiv.

- [ ] **Step 4: Test laufen lassen, PASS bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_endpoint_resolution.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/bridge_common.py scripts/test_endpoint_resolution.py
git commit -m "feat(bridge): this_endpoint() per hostname auto-detect (override-first)"
```

---

## Task 2: conftest zwingt Default-Endpoint pro Test

**Files:**
- Modify: `scripts/conftest.py` (autouse-Fixture `_isolate_dual_bridge_state`, im Block wo `DUAL_BRIDGE_ROOT`/`DUAL_BRIDGE_LOCK` gesetzt werden)

Dies behebt die 6 Tests, die auf einer Maschine mit abweichendem `setx DUAL_BRIDGE_ENDPOINT` rot werden (sie gehen vom Default-Endpoint `claude@laptop-a` aus).

- [ ] **Step 1: Verifizieren, dass die Tests OHNE Default-Zwang rot sind (Baseline-RED)**

Run (simuliert den geleakten Maschinen-Endpoint):
`cd scripts && DUAL_BRIDGE_ENDPOINT=codex@laptop-b python -X utf8 -m pytest test_stage1.py::test_write_includes_repo_fields test_pingpong_realbuild.py -q`
Expected: FAIL (6 failed) — exakt die im Spec beschriebenen Fehler.

- [ ] **Step 2: Fixture-Änderung**

In `scripts/conftest.py`, in der autouse-Fixture direkt nach den beiden Zeilen, die `DUAL_BRIDGE_LOCK` setzen (vor `_ensure_runners_registered()`), einfügen:

```python
    # Force a deterministic endpoint so the suite never depends on a machine's
    # persistent `setx DUAL_BRIDGE_ENDPOINT`. Several tests assume the DEFAULT
    # node (claude@laptop-a -> lane A-to-B); a leaked codex@laptop-b flips the
    # lane and they fail spuriously (Wiki-TODO P2). A test that needs the other
    # endpoint still overrides DUAL_BRIDGE_ENDPOINT itself.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
```

Da der `finally`-Block bereits ALLE `DUAL_BRIDGE_*`-Keys gegen den `snapshot` zurücksetzt (nicht-Snapshot-Keys werden gelöscht, Snapshot-Keys restauriert), wird auch dieser Endpoint korrekt zurückgerollt — keine zusätzliche Teardown-Zeile nötig.

- [ ] **Step 3: Verifizieren, dass die Tests jetzt grün sind — AUCH mit geleaktem Maschinen-Endpoint**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=codex@laptop-b python -X utf8 -m pytest test_stage1.py::test_write_includes_repo_fields test_stage1.py::test_collect_shows_pull_hint test_pingpong_realbuild.py -q`
Expected: PASS (6 passed) — der conftest-Zwang überschreibt den geleakten Endpoint pro Test.

- [ ] **Step 4: Endpoint-Resolution-Tests bleiben grün (sie monkeypatchen selbst)**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=codex@laptop-b python -X utf8 -m pytest test_endpoint_resolution.py -q`
Expected: PASS (5 passed) — diese Tests setzen den Endpoint selbst via monkeypatch, der conftest-Default stört nicht.

- [ ] **Step 5: Commit**

```bash
git add scripts/conftest.py
git commit -m "test(bridge): conftest forces default endpoint per test (fixes setx leak)"
```

---

## Task 3: `_pid_alive()` Cmdline-Marker-Check (Kernlogik, plattform-getestet)

**Files:**
- Modify: `scripts/bridge_common.py` (`_pid_alive`, ~Z438; ggf. Helper `_pid_cmdline`)
- Test: `scripts/test_pid_liveness.py` (neu)

- [ ] **Step 1: Failing-Test schreiben**

Datei `scripts/test_pid_liveness.py`:

```python
"""Tests for _pid_alive() identity-aware liveness (anti PID-recycling, L11)."""
from __future__ import annotations

import os
import bridge_common as bc


def test_no_match_arg_keeps_existence_only_behavior(monkeypatch):
    # Without must_match, an existing pid is alive regardless of cmdline.
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "anything")
    assert bc._pid_alive(os.getpid()) is True


def test_dead_pid_is_not_alive():
    assert bc._pid_alive(-1) is False
    assert bc._pid_alive(0) is False


def test_recycled_pid_without_marker_is_stale(monkeypatch):
    # PID exists but its cmdline is a recycled svchost -> not OUR poller.
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: r"C:\Windows\system32\svchost.exe -k netsvcs")
    assert bc._pid_alive(1234, must_match="handoff_poll") is False


def test_matching_marker_is_alive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(
        bc, "_pid_cmdline",
        lambda pid: r"python -X utf8 C:\...\scripts\handoff_poll.py --watch")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_marker_match_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: r"python HANDOFF_POLL.PY --watch")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_failed_cmdline_query_is_conservatively_alive(monkeypatch):
    # Query failed (empty) but the pid exists -> assume alive, never false-negative
    # a real running poller into a double-claim.
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "")
    assert bc._pid_alive(1234, must_match="handoff_poll") is True


def test_marker_required_but_pid_dead_is_not_alive(monkeypatch):
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: False)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "handoff_poll")
    assert bc._pid_alive(1234, must_match="handoff_poll") is False
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_pid_liveness.py -q`
Expected: FAIL — `_pid_alive` kennt `must_match` noch nicht; `_pid_exists`/`_pid_cmdline` existieren noch nicht (AttributeError beim monkeypatch).

- [ ] **Step 3: Implementierung**

In `scripts/bridge_common.py`: Die bestehende `_pid_alive`-Existenzprüfung in einen Helper `_pid_exists` ausgliedern, einen `_pid_cmdline`-Helper hinzufügen, und `_pid_alive` um `must_match` erweitern.

Bestehende `_pid_alive(pid)` ersetzen durch:

```python
def _pid_exists(pid: int) -> bool:
    """True if a process with `pid` currently exists on this OS (existence only)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        out = _subprocess_run_quiet(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"]
        )
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_cmdline(pid: int) -> str:
    """Best-effort command line of `pid`, or "" if it can't be determined.

    Windows: tasklist carries no cmdline -> Get-CimInstance Win32_Process. POSIX:
    /proc/<pid>/cmdline (NUL-separated). An empty return means "unknown" and the
    caller treats it conservatively (see _pid_alive). Never raises."""
    if pid <= 0:
        return ""
    if os.name == "nt":
        out = _subprocess_run_quiet([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
            f".CommandLine",
        ])
        return out.strip()
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _pid_alive(pid: int, must_match: str | None = None) -> bool:
    """True if `pid` is a live process. With must_match, additionally require the
    process command line to contain that marker (case-insensitive) -- this is the
    anti-PID-recycling guard (L11): a recycled svchost holding our old pid has a
    different cmdline and is correctly seen as stale.

    Fail-safe: if the pid exists but its cmdline can't be read (empty), assume
    alive. Never false-negative a real running poller into a double-claim."""
    if not _pid_exists(pid):
        return False
    if must_match is None:
        return True
    cmdline = _pid_cmdline(pid)
    if not cmdline:
        return True  # conservative: exists but cmdline unknown -> assume ours
    return must_match.lower() in cmdline.lower()
```

(Der bestehende `_subprocess_run_quiet`-Helper mit `encoding="oem"` + `stdin=DEVNULL` bleibt unverändert und wird von beiden Helpern genutzt.)

- [ ] **Step 4: Test laufen lassen, PASS bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_pid_liveness.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/bridge_common.py scripts/test_pid_liveness.py
git commit -m "fix(bridge): _pid_alive() cmdline-match guards against PID recycling (L11)"
```

---

## Task 4: `acquire_singleton_lock()` nutzt den Marker-Check

**Files:**
- Modify: `scripts/bridge_common.py` (`acquire_singleton_lock`, ~Z477)
- Test: `scripts/test_pid_liveness.py` (append)

- [ ] **Step 1: Failing-Test schreiben (append an `test_pid_liveness.py`)**

```python
def test_lock_taken_over_when_holder_is_recycled_pid(tmp_path, monkeypatch):
    """A lockfile holding a live-but-foreign pid (recycled) must be taken over,
    not block a restart -- the exact 06-05 stale-lock incident."""
    lock = tmp_path / "poller.lock"
    lock.write_text("999999\n2026-06-05T22:01:00\n", encoding="utf-8")
    # 999999 'exists' (recycled) but its cmdline is NOT our poller.
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline", lambda pid: "svchost.exe -k netsvcs")
    assert bc.acquire_singleton_lock(lock) is True
    # Lock now carries OUR pid.
    assert lock.read_text(encoding="utf-8").splitlines()[0].strip() == str(os.getpid())


def test_lock_blocked_when_real_poller_holds_it(tmp_path, monkeypatch):
    lock = tmp_path / "poller.lock"
    lock.write_text("888888\n2026-06-06T19:00:00\n", encoding="utf-8")
    monkeypatch.setattr(bc, "_pid_exists", lambda pid: True)
    monkeypatch.setattr(bc, "_pid_cmdline",
                        lambda pid: r"python handoff_poll.py --watch")
    assert bc.acquire_singleton_lock(lock) is False
```

- [ ] **Step 2: Test laufen lassen, FAIL bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_pid_liveness.py -k lock -q`
Expected: FAIL — `acquire_singleton_lock` ruft `_pid_alive(held_pid)` noch OHNE `must_match`, behandelt die recycelte PID also als lebend → `test_lock_taken_over...` schlägt fehl (return False statt True).

- [ ] **Step 3: Implementierung**

In `acquire_singleton_lock()` die eine Liveness-Zeile ändern. Vorher:

```python
        if held_pid != os.getpid() and _pid_alive(held_pid):
            return False  # a live poller holds it
```

Nachher:

```python
        if held_pid != os.getpid() and _pid_alive(held_pid, must_match="handoff_poll"):
            return False  # a live poller (verified by cmdline) holds it
```

- [ ] **Step 4: Test laufen lassen, PASS bestätigen**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest test_pid_liveness.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/bridge_common.py scripts/test_pid_liveness.py
git commit -m "fix(bridge): singleton lock verifies holder identity (cmdline) before blocking"
```

---

## Task 5: Volle Suite grün + Drive-Isolation snapshot-bewiesen

**Files:** keine (Verifikation).

- [ ] **Step 1: Snapshot der echten Drive-Row-Counts/Dateien VOR dem Lauf**

Run:
```
powershell -Command "(Get-ChildItem -Recurse 'G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge' -File | Measure-Object).Count"
```
Wert notieren (Baseline).

- [ ] **Step 2: Volle Suite mit geleaktem Maschinen-Endpoint (Härtetest)**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=codex@laptop-b python -X utf8 -m pytest -q`
Expected: alle grün (die conftest aus Task 2 zwingt den Default; die 6 vormals roten Tests sind grün). Soll-Zahl: vorheriges Grün + 14 neue Tests (5 Endpoint + 9 Liveness).

- [ ] **Step 3: Volle Suite mit Default-Endpoint (Kontrolle)**

Run: `cd scripts && DUAL_BRIDGE_ENDPOINT=claude@laptop-a python -X utf8 -m pytest -q`
Expected: identisch grün.

- [ ] **Step 4: Snapshot NACH dem Lauf — Isolation beweisen**

Run denselben Count-Befehl wie Step 1.
Expected: identische Zahl. Bei Abweichung → STOP, Isolation verletzt (globale Regel §3), Ursache klären bevor weiter.

- [ ] **Step 5: kein Commit** (reine Verifikation; nächster Commit ist die Doku).

---

## Task 6: Doku + Migrationsnotiz

**Files:**
- Modify: `README.md` (Env-Vars/Endpoint-Abschnitt)
- Modify: `CLAUDE.md` (Abschnitt „Tasks initiieren" / Endpoint-Hinweis)

- [ ] **Step 1: README ergänzen**

Im Endpoint-/Env-Var-Abschnitt von `README.md` einen Absatz ergänzen (passende Stelle per Grep `DUAL_BRIDGE_ENDPOINT` finden):

```markdown
### Endpoint-Identität (Maschine, nicht Agent)

Der Endpoint bestimmt die **Lane-Richtung** und hängt an der **Maschine**, nicht an
Rolle oder Agent. `this_endpoint()` löst dreistufig auf:

1. `DUAL_BRIDGE_ENDPOINT` (per `setx`) — expliziter Override, höchster Vorrang.
2. Hostname-Auto-Erkennung (case-insensitiv): `DOME-DYNAMICS → codex@laptop-b`,
   `K472HEXXZACKBUU → claude@laptop-a`.
3. Unbekannter Host ohne Override → klarer Fehler (kein stilles Raten).

Der `claude@`/`codex@`-Präfix ist kosmetisch; der real laufende Adapter kommt
ausschließlich aus dem Task-Feld `adapter:`. **Migration:** Bestehende
`setx DUAL_BRIDGE_ENDPOINT`-Werte bleiben als Override gültig — kein koordinierter
Umstieg über beide Laptops nötig. Neue Maschine → entweder Hostname in
`HOSTNAME_TO_ENDPOINT` (`scripts/bridge_common.py`) eintragen oder `setx` setzen.
```

- [ ] **Step 2: CLAUDE.md ergänzen**

In `CLAUDE.md` beim Endpoint-Hinweis im Abschnitt „Tasks initiieren" ergänzen:

```markdown
> **Endpoint = Maschine, hostname-erkannt.** `this_endpoint()` leitet die Identität
> automatisch aus dem Hostname ab (Override via `setx DUAL_BRIDGE_ENDPOINT` bleibt
> vorrangig). Agent/Adapter kommt aus `adapter:`, nicht aus dem Endpoint-Namen.
```

- [ ] **Step 3: Doku-Claims gegen Code prüfen**

Run: `cd scripts && python -X utf8 -c "import bridge_common as bc; print(bc.HOSTNAME_TO_ENDPOINT)"`
Expected: zeigt exakt die in der Doku genannten Mappings.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs(bridge): endpoint = machine (hostname auto-detect) + migration note"
```

---

## Task 7: Wiki-TODO schließen

**Files:**
- Modify: `C:/Users/domes/wiki/wiki/todos/2026-06-05-dual-bridge-endpoint-schema-maschine-statt-agent.md`

- [ ] **Step 1: Status + Log aktualisieren**

Frontmatter `status: open` → `status: done`, `updated: 2026-06-06`. Die Akzeptanz-Checkboxen abhaken. Im `## Log` einen Eintrag ergänzen:

```markdown
- 2026-06-06 erledigt: hostname-Auto-Erkennung (override-first) + _pid_alive cmdline-match
  + conftest-Endpoint-Default. Spec/Plan unter docs/superpowers/{specs,plans}/2026-06-06-*.
  Suite grün auch mit geleaktem Maschinen-setx, Drive-Isolation snapshot-bewiesen.
```

- [ ] **Step 2: Commit (Wiki ist eigenes Repo)**

```bash
cd C:/Users/domes/wiki && git add wiki/todos/2026-06-05-dual-bridge-endpoint-schema-maschine-statt-agent.md && git commit -m "todo(dual-bridge): endpoint-schema P2 erledigt"
```

(Nur diese eine Datei stagen — §7 chirurgisch; fremde Wiki-Drift nicht mitnehmen.)

---

## Self-Review (vom Plan-Autor)

- **Spec-Coverage:** Endpoint-Auflösung (T1), conftest-Default (T2), Liveness-Cmdline (T3), Lock-Aufrufer (T4), Suite+Isolation (T5), Doku+Migration (T6), TODO-Abschluss (T7) — alle Spec-Abschnitte abgedeckt.
- **Platzhalter:** keine; jeder Code-Step zeigt vollständigen Code + exakten Befehl + erwartete Ausgabe.
- **Typ-Konsistenz:** `_pid_exists`/`_pid_cmdline`/`_pid_alive(pid, must_match)` durchgängig gleich benannt; `HOSTNAME_TO_ENDPOINT` uppercase-Keys + `host.upper()` konsistent; conftest-Key `DUAL_BRIDGE_ENDPOINT` = der von `this_endpoint()` gelesene.
