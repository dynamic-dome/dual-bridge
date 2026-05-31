# Gate Phase 6 — Two-Device-Proof: Pickup für Laptop B

Ziel: beweisen, dass der **Pre-Tool-Use-Gate** end-to-end über zwei Geräte
funktioniert. A versucht eine riskante Aktion → Hook blockt mit `gate_id` →
`gate_bridge` schickt einen `kind: review`-Task an B → **B reviewt mit echtem
`claude -p`** und gibt ein `VERDICT: accepted|rejected` zurück → A liest das
Verdikt per `gate_id` → Aktion wird erlaubt/abgelehnt.

> B ist diesmal der **Reviewer** (nicht codex-Worker wie in Stage 1). Der
> Unterschied: Adapter `claude`, `kind: review`, **kein Repo**. Der Reviewer
> muss seine Antwort mit genau einer Markerzeile beenden:
> `VERDICT: accepted` oder `VERDICT: rejected`.

---

## 0. Repo aktualisieren (Phase 0 wird gebraucht!)

Die Verdikt-Semantik (parse_verdict + gate_id-Spiegelung) kam erst mit Phase 0.
B muss mindestens auf Commit `d99cc8b` sein:

```powershell
cd C:\Users\domes\AI\dual-bridge
git pull            # Ziel: d99cc8b oder neuer
git log --oneline -1
```

## 1. Setup-Check fahren (self-diagnostizierend)

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
$env:DUAL_BRIDGE_ENDPOINT = "codex@laptop-b"     # PFLICHT - sonst pollt B die falsche Lane
powershell -ExecutionPolicy Bypass -File gate-setup-check-B.ps1
```

Das Skript druckt `KEY=VALUE`-Zeilen. **Alles muss `OK` / `READY` sein.** Die
wichtigsten:
- `CLAUDE_BIN=OK` — der Reviewer braucht `claude` im PATH (oder `DUAL_BRIDGE_CLAUDE_BIN`).
- `ENDPOINT=OK (codex@laptop-b)` — sonst sieht B die A-to-B-Lane nicht.
- `BRIDGE_ROOT=OK` — Google-Drive gemountet (sonst `DUAL_BRIDGE_ROOT` setzen).
- `PHASE0_REVIEW_VERDICT=OK` — sonst hast du noch nicht gepullt.

Wenn `RESULT=NOT-READY`: die failende Zeile fixen, erneut laufen. Die ganze
Ausgabe kannst du als Textblock an A zurückschicken (Rückkanal).

## 2. Poller starten (sichtbares Terminal)

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
$env:DUAL_BRIDGE_ENDPOINT = "codex@laptop-b"
python handoff_poll.py --watch
```

Läuft passiv, pollt alle ~15 s. Doppelstart ist durch den Singleton-Lock
unmöglich. Mit Strg+C beenden.

→ **Jetzt ist B bereit.** Sag A Bescheid (Rückkanal); A löst den Gate aus.

---

## 3. Was auf A passiert (zur Orientierung — A fährt das selbst)

1. A startet einen Loop mit `--gate-mode enforce` auf einem **harmlosen**
   Wegwerf-Workflow (Threat-Model: enforce NUR auf Harmlosem, solange
   secret-sweep/deploy-safety fehlen).
2. Eine riskante Tool-Aktion (z.B. `Bash: git push`) wird vom PreToolUse-Hook
   **denied** — der Reason enthält die `gate_id`.
3. A ruft `gate_bridge.write_gate_task(request)` → ein `task-<id>.md` mit
   `kind: review`, `adapter: claude`, `gate_id: …` landet in
   `lane-A-to-B/outbox`.

## 4. Was B tut (automatisch, sobald der Poller läuft)

- B claimt den Task aus `lane-A-to-B/outbox`.
- Routet `adapter: claude` → echter `claude -p`-Aufruf mit dem Review-Prompt.
- Der Reviewer beurteilt adversarial und endet mit `VERDICT: accepted` /
  `VERDICT: rejected`.
- B schreibt das Result nach `lane-A-to-B/inbox` mit gespiegeltem `gate_id` +
  `verdict`. (Fail-closed: unklare Antwort → `rejected`.)

## 5. Ground-Truth-Prüfung auf A (P007 — status NICHT blind glauben)

A liest das Verdikt per `gate_bridge.collect_result(gate_id)` und **liest die
Result-Datei real gegen**:
```powershell
# Result-Datei in lane-A-to-B/inbox öffnen, prüfen:
#  - gate_id stimmt mit dem geblockten Gate überein
#  - verdict-Feld plausibel zum Review-Text
#  - der Reviewer-Text endet wirklich mit der VERDICT-Markerzeile
```
Erst dann gilt der Gate als bewiesen. Bei `accepted` → die Aktion auf A wird
erlaubt; bei `rejected` → bleibt geblockt.

## 6. Fehlerpfad einmal real sehen (empfohlen)

Einen zweiten Gate auslösen, bei dem der Reviewer `rejected` zurückgibt (oder
eine leere/markerlose Antwort → fail-closed `rejected`). Beweist, dass der Gate
auch wirklich blockiert, nicht nur durchwinkt.

---

## Env-Variablen (B-Reviewer)

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ENDPOINT` | **PFLICHT** `codex@laptop-b` (sonst falsche Lane) | `claude@laptop-a` |
| `DUAL_BRIDGE_ROOT` | Bridge-Root falls Drive-Letter auf B anders | Drive-Pfad |
| `DUAL_BRIDGE_CLAUDE_BIN` | expliziter `claude`-Pfad | `shutil.which("claude")` |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für den Runner | `~/dual-bridge-work` |
| `DUAL_BRIDGE_DEVICE` | Geräte-Label im Claim | `COMPUTERNAME` |

## Troubleshooting

- **Task kommt nie an / Poller sieht nichts** → `DUAL_BRIDGE_ENDPOINT` nicht auf
  `codex@laptop-b`? Dann pollt B die falsche Lane. Häufigster Fehler.
- **`claude nicht gefunden`** im Result → `claude` nicht im PATH auf B;
  `DUAL_BRIDGE_CLAUDE_BIN` setzen.
- **Result hat `verdict: rejected` mit "no VERDICT marker found"** → der
  Reviewer hat die Markerzeile vergessen. Fail-closed ist korrekt; der
  Review-Prompt fordert die Zeile explizit, ein erneuter Lauf hilft meist.
- **`status: error`** im Result → Reviewer-Subprozess failte; `error_text` /
  `stderr_excerpt` im Result lesen.
