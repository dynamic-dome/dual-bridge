# Design: Risk-Level-Mapping (Bridge-kind/adapter → Risk-Levels)

*Datum: 2026-06-12 · Status: approved (Design-Session, User-abgesegnet)*
*Herkunft: erweiterungsliste.md 2.5 → Triage 2026-06-11 §2 „Interaktive Design-Sessions" #1*

## Problem

Die Task-Felder `kind` und `adapter` sind heute reine Etiketten ohne
Sicherheits-Wirkung: kein Code prüft, ob ein Task tun darf, was er
beschreibt. Ein `kind: review`-Task mit `adapter: codex` könnte bauen und
pushen; ein Auftragstext könnte Ops-Aktionen anweisen (Scheduled Tasks
registrieren, in die Base mergen, Admin-Befehle). Die Lane liegt auf Google
Drive — ein manipulierter oder „kreativ erweiterter" Task ist die
Bedrohungsklasse. Kernsatz des Originalvorschlags: **kein Admin-Exec über
die Bridge.**

## Ziel und Nicht-Ziele

**Ziel:** Eine enforced, deklarative Policy — kind/adapter → Risk-Level →
erlaubte Aktionen — fail-closed an Sender und Empfänger. Bestehende
Workflows (Goal-Loops, DCO-Autoqueue, Overnight-Seeds) laufen unverändert;
abgelehnt werden nur Kombinationen, die heute schon nicht vorgesehen sind.

**Nicht-Ziele:**
- Keine DCO-Feld-Durchreichung (Ansatz C der Session, vertagt bis ein
  DCO-Konsument das Feld liest).
- Kein Diff-Scan — gebaute Diffs prüft weiterhin `loop_driver.scan_dangerous`
  (`DANGEROUS_PATTERNS`); der Ops-Scan hier läuft NUR über den Auftragstext
  (Gate-vs-Gate-Lehre L12: Regex-Muster im generierten Artefakt dürfen die
  Policy nicht triggern).
- Keine Änderung an der Eskalationslogik des Goal-Loops.

## Skala (3 Stufen, geordnet)

| Level | Bedeutung | Beispiele |
|---|---|---|
| `read` | Lesen + Text antworten, kein Repo-Write | echo-Smoke, Review, Recherche |
| `build` | Klonen, committen, Push auf `bridge/...`-Branches in Allowlist-Repos | implement, test |
| `ops` | Scheduled Tasks, Merge/Push in die Base, Admin | **nie über die Bridge** — nur interaktiv |

`ops` existiert als Level, aber kein `kind` erreicht es — „kein Admin-Exec
über die Bridge" ist damit strukturell codiert, nicht nur Konvention.
DCO-Bezug: das DCO-Risk-System (`admin.py`, `standard`/`elevated`) mappt
konzeptionell auf `ops` = nur in einer PIN-bestätigten interaktiven
Admin-Session, nie über einen Bridge-Task.

## Komponente: `scripts/risk_policy.py` (neu)

Vorbild `secret_gate.py`: klein, eigenständig, ohne Bridge-I/O, testbar.

```python
LEVELS = ("read", "build", "ops")

KIND_LEVEL = {
    "echo": "read", "review": "read", "research": "read",
    "implement": "build", "test": "build",
}
ADAPTER_CAPABILITY = {
    "echo": "read", "claude": "read",
    "codex": "build", "increment": "build",
}
OPS_PATTERNS = [
    r"\bschtasks\b",
    r"\b(Un)?[Rr]egister-ScheduledTask\b",
    r"\bgit\s+push\s+\S*\s+(main|master)\b",
    r"\bmerge\b.{0,40}\b(main|master)\b",
    r"\bADMIN_PIN\b",
    r"^/admin\b",
]

def check_task(kind: str, adapter: str, body: str) -> Violation | None: ...
```

Drei Regeln (erste Verletzung gewinnt, Rückgabe trägt Regel-Key + Begründung):

- **R1 — Level-Mismatch:** `ADAPTER_CAPABILITY[adapter] != KIND_LEVEL[kind]`
  → Ablehnung. Deckt beide Richtungen: bauender Adapter auf read-Task
  (Eskalation) UND read-Adapter auf build-Task (heutiges Spät-Leise-Scheitern,
  Memory `claude-adapter-is-review-only-no-build` vom 06-09 — die damalige
  „kein Guard"-Entscheidung wird hiermit bewusst revidiert, weil die
  Policy-Tabelle jetzt der richtige Ort ist; claude-Builder später =
  Ein-Zeilen-Änderung `"claude": "build"`).
- **R2 — Ops-Verben im Auftragstext:** OPS_PATTERN-Treffer im Body →
  Ablehnung mit Pattern-Nennung. Bewusst akzeptierte kleine
  False-Positive-Fläche (z.B. „dokumentiere, wie man Scheduled Tasks
  registriert") — Ablehnung ist sichtbar im Result, Umformulieren möglich.
- **R3 — fail-closed bei Drift:** unbekanntes `kind` oder `adapter` → wie
  `ops` = Ablehnung. Ein neuer Wert zwingt zur bewussten Policy-Entscheidung.

Patterns liegen im Code (Vorbild `DANGEROUS_PATTERNS`), NICHT in
`config.json` — ein Security-Gate ist nicht soft-konfigurierbar.

## Enforcement-Punkte

| Punkt | Wann | Bei Verstoß |
|---|---|---|
| `handoff_poll` (Empfänger = Sicherheitsgrenze) | nach Claim, vor Runner-Dispatch | Result `status: error`, `error_text: risk_policy:<regel>: <grund>`, Task → `_processed/` — Sender sieht die Begründung, nichts hängt |
| `job_poll` (DCO-Pfad) | Seed-Check vor Loop-Start | Job-Result error, Todo bleibt offen |
| `handoff_write` (Sender = Frühwarnung) | vor dem Schreiben in die Outbox | Exit ≠ 0 mit Begründung; **kein Override-Flag** (anders als `--allow-secrets`: es gibt keinen legitimen Ops-Task über die Bridge) |

Alle drei rufen dieselbe `check_task()` — eine Quelle, kein Drift.

## Vorarbeit: loop_driver-Etikett korrigieren (Pflicht, selber Slice)

Spec-Self-Review-Fund: `loop_driver.write_round_task` (Z. 299) hartkodiert
`kind: "echo"` für ALLE Runden-Tasks — auch wenn `adapter=codex` baut
(Ping-Pong-Modus). R1 würde diesen produktiven Flow ablehnen. Fix gehört in
denselben Slice, VOR Aktivierung des Empfänger-Checks:
`kind = "implement" if repo else "echo"` (bauende Runden-Tasks tragen das
ehrliche Etikett; Text-Runden bleiben echo). `write_review_task` ist korrekt
(`kind: review` + `adapter: claude`).

## Fehlerbehandlung

- Ablehnung ist nie eine Exception nach oben: bestehende
  „no stuck, no silent failure"-Semantik (CodexResult-Muster) gilt.
- `check_task` selbst wirft nicht; kaputte Eingaben (None/leer) → R3.

## Tests (pytest, bestehende Suite)

1. Tabellengetrieben: alle kind×adapter-Kombos gegen erwartetes Verdikt.
2. Ops-Scan positiv (jedes Pattern) + negativ (harmlose Texte, u.a.
   False-Positive-Kandidaten wie „review the scheduler docs").
3. R3: unbekannte Werte, None, leere Strings.
4. Integration `handoff_poll`: Claim → Ablehnung → Result in Lane,
   Task in `_processed/` (isoliertes tmp_path-Bridge-Root, Regel §3).
5. Integration `handoff_write`: Ops-Task wird nicht geschrieben, Exit ≠ 0.
6. **Drift-Test:** argparse-`choices` für `--kind`/`--adapter` in
   `handoff_write` == Keys von `KIND_LEVEL`/`ADAPTER_CAPABILITY` —
   neues kind ohne Policy-Eintrag macht die Suite rot.

## Betriebsauswirkung

Keine für bestehende Flows: alle produktiven Kombinationen
(echo/echo, implement/codex, test/codex, review/claude, research/claude)
sind erlaubt. Ping-Pong-Runden-Tasks brauchen die Etikett-Korrektur
(siehe Vorarbeit), dann erlaubt als implement/codex. NEU abgelehnt:
review+codex, implement+claude (vorher spät-leise kaputt), jeder Task
mit Ops-Verben im Auftrag.
