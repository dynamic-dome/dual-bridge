# Design: Endpoint-Schema (Maschinen-ID per Hostname) + Stale-PID-Liveness-Fix

*Datum: 2026-06-06*
*Quelle: Wiki-TODO P2 `2026-06-05-dual-bridge-endpoint-schema-maschine-statt-agent.md`*
*Status: approved (User), bereit für writing-plans*

## Problem

Zwei am 2026-06-05 live aufgedeckte Robustheits-Lücken, die zusammen aus einem
trivialen Konfig-Dreher einen schwer auffindbaren Hänger machten (3 `kind:review`-
Tasks blieben auf Lane A-to-B liegen).

**1. Endpoint-Label vermischt Maschine + Agent.** `this_endpoint()` defaultet hart
auf `claude@laptop-a` und der Endpoint-String mischt drei unabhängige Dinge:
- **Maschine** (`laptop-a`/`laptop-b`) → bestimmt die Lane-Richtung — das einzige,
  was tatsächlich zählt.
- **Agent** (`claude`/`codex`) → bestimmt **nichts**; der reale Adapter kommt aus
  dem Task-Feld `adapter:` (`handoff_poll.py`).
- **Rolle** (Builder/Reviewer) → nur implizit in der Lane-Richtung.

Folge: Sobald sich Rollen drehen, passt das Präfix nicht mehr; Menschen und Commits
(`dbfe478`) verwechseln „claude vs codex" mit „a vs b". Zusätzlich macht der harte
Default die Test-Suite auf einer Maschine mit abweichendem `setx` rot (6 Tests, die
vom Default-Endpoint ausgehen).

**2. Stale-PID-Liveness-False-Positive.** `_pid_alive()` prüft nur, ob *irgendein*
Prozess mit der Lock-PID existiert (`tasklist /FI "PID eq N"`), nicht ob es **der
eigene Poller** ist. Am 06-05 trug das Lockfile PID 11176 vom Vortag; Windows hatte
sie an `svchost` recycelt → `bridge_status.py` meldete fälschlich „poller LÄUFT" und
`acquire_singleton_lock()` hätte einen Neustart blockiert. Exakt die L11/L7-Klasse.

## Teil 1 — Endpoint aus Maschine ableiten

### Neue Komponente (`bridge_common.py`)

```python
HOSTNAME_TO_ENDPOINT = {
    "DOME-DYNAMICS":   "codex@laptop-b",
    "K472HEXXZACKBUU": "claude@laptop-a",
}
```

### Auflösungslogik (`this_endpoint()`)

Dreistufig, override-zuerst:

1. `DUAL_BRIDGE_ENDPOINT` gesetzt → nutze das (Notnagel, höchster Vorrang).
2. Sonst: `socket.gethostname()` **case-insensitiv** gegen `HOSTNAME_TO_ENDPOINT`
   → voller Endpoint-String.
   (Ground-Truth: `gethostname()` liefert `DoMe-Dynamics` in gemischter Schreibung,
   die Drive-Claims tragen `DOME-DYNAMICS` — case-insensitives Matching ist Pflicht.)
3. Host unbekannt **und** kein Override → `ValueError` mit handlungsanweisendem Text
   (welcher Hostname erkannt wurde, wie man `setx DUAL_BRIDGE_ENDPOINT=...` setzt),
   statt still auf `claude@laptop-a` zu raten.

### Bewusst unverändert (minimal-invasiv, kein Bruch)

- `ENDPOINTS`-Keys bleiben die vollen `claude@laptop-a`/`codex@laptop-b`-Strings.
- `register_watchdog.ps1 -Endpoint ValidateSet` bleibt unverändert.
- Der Agent-Präfix im String bleibt kosmetisch/historisch; die Lane-Richtung wird
  nun automatisch pro Maschine korrekt. Adapter kommt weiter ausschließlich aus
  `adapter:`.

## Teil 2 — Stale-PID-Liveness-Fix (Cmdline-Match)

### Geänderte Komponente (`_pid_alive()`)

Signatur erweitern: `_pid_alive(pid, must_match=None)`.

- `must_match=None` (Default) → altes Verhalten (reine Existenz), kein Aufrufer bricht.
- `must_match="handoff_poll"` → `True` nur, wenn die PID existiert **und** ihre
  CommandLine den Marker (case-insensitiv) enthält.

Plattform-Pfade:
- **Windows:** `tasklist` liefert keine Cmdline → `Get-CimInstance Win32_Process
  -Filter "ProcessId=<pid>"` (Property `CommandLine`), Dekodierung wie der
  bestehende `_subprocess_run_quiet` (encoding `oem`).
- **POSIX:** `/proc/<pid>/cmdline` (Fallback `ps`), Marker prüfen.

### Aufrufer

`acquire_singleton_lock()` ruft `_pid_alive(held_pid, must_match="handoff_poll")`.
Eine recycelte Fremd-PID fällt durch → Lock gilt als stale → automatisch übernommen
(Neustart nicht mehr blockiert). `bridge_status.py` nutzt denselben Pfad → meldet
nicht mehr fälschlich „poller LÄUFT".

### Fail-safe-Härtung

Schlägt die Cmdline-Abfrage selbst fehl (Berechtigung, Tool fehlt, leere Ausgabe
trotz existierender PID), darf das **nicht** zu einem False-Negative führen, das
einen echten laufenden Poller fälschlich als tot deklariert (→ Doppel-Start/Doppel-
Claim). Entscheidung: bei nicht-eindeutiger Abfrage **konservativ „lebt" annehmen**
(lieber Neustart blockieren als doppelt claimen). Der reale Vorfall — recycelte PID
liefert sauber eine *andere* Cmdline ohne Marker — wird trotzdem korrekt als stale
erkannt, weil dort die Abfrage erfolgreich ist und der Marker schlicht fehlt.

## Testplan (TDD)

**Endpoint:**
- Override-Vorrang (`DUAL_BRIDGE_ENDPOINT` schlägt Hostname).
- Bekannter Hostname case-insensitiv, beide Maschinen → korrekter Endpoint.
- Unbekannter Host ohne Override → `ValueError` mit Hinweistext.
- Lane-Richtung pro Maschine korrekt (`receive_lanes`/`send_lane`).

**Liveness:**
- Eigene PID + Marker → lebt.
- Recycelte Fremd-PID (Marker fehlt, Abfrage erfolgreich) → stale → Lock übernommen.
- Fehlgeschlagene/leere Abfrage → konservativ „lebt".
- `must_match=None` → altes Verhalten (reine Existenz).

**conftest:**
- Endpoint in der Isolations-Fixture auf einen Default zwingen, damit die Suite
  unabhängig vom `setx` der Maschine grün ist (behebt die 6 roten Tests).

**Abschluss:**
- `cd scripts && python -X utf8 -m pytest -q` grün.
- Drive-Isolation snapshot-bewiesen (Poison-Guard unverändert wirksam).

## Doku

- README + CLAUDE.md: Endpoint = Maschine (hostname-erkannt), Agent/Adapter strikt
  aus `adapter:`.
- Migrationsnotiz: `setx DUAL_BRIDGE_ENDPOINT` wird optional; die bestehenden Werte
  auf beiden Laptops bleiben als Override gültig → kein koordinierter Umstieg nötig.

## Akzeptanzkriterien (aus Wiki-TODO)

- [ ] Endpoint-Identität aus Maschine abgeleitet (hostname), Agent/Adapter vom
      Endpoint-Namen entkoppelt — dokumentiert.
- [ ] `_pid_alive()`/Liveness prüft PID **und** Prozess-Identität (Cmdline), kein
      Recycling-False-Positive; Regressionstest mit Fremd-PID.
- [ ] Migrationspfad für bestehende `setx`-Werte beschrieben (Override bleibt gültig).
- [ ] `ENDPOINTS` + `register_watchdog.ps1 ValidateSet` konsistent (hier: bewusst
      unverändert, da Auto-Erkennung auf die vollen Strings abbildet).
- [ ] Suite grün, Drive-Isolation snapshot-bewiesen.

## Out of Scope

- Reine `laptop-a`/`laptop-b`-Endpoint-Keys (Agent endgültig aus dem String
  entfernen) — bewusst vertagt; die Auto-Erkennung auf die vollen Strings löst das
  akute Problem ohne ValidateSet-/Doku-Bruch.
- Mojibake im B-Worker-stdout (latin-1→UTF-8) — separater Sprint.
