# PICKUP — Stage 3 Goal-Loop Live-Proof (beide Pfade + Reseed-Resume)

Ziel: Den `--mode goal-loop` cross-device live beweisen — **echter** codex baut (A),
**echtes** claude reviewt den Diff gegen die Done-Kriterien (B). Ein Lauf soll
**Fortschritt UND Eskalation** zeigen, danach ein **Reseed-Resume** bis `accepted`.
Fakes beweisen nur Mechanik (P006/P009); dies ist der Vertragsbeweis.

Voraussetzung: beide Geräte haben `dual-bridge` auf `main` == `origin/main`
(`d7f2be2` oder neuer). B hat codex 0.135+ und ein eingeloggtes claude-Abo.

---

## Schritt 1 — B (Mensch an Laptop B): Reviewer-Poller starten

```powershell
cd C:\Users\domes\AI\dual-bridge
git pull                                  # auf d7f2be2 oder neuer
cd scripts
$env:DUAL_BRIDGE_ENDPOINT = 'claude@laptop-b'   # B reviewt = claude
python handoff_poll.py --watch --interval 10
```

B läuft jetzt und wartet auf `kind:review`-Tasks. Laufen lassen.

## Schritt 2 — A (hier): Goal-Loop starten

Der Seed liegt in `docs/live-proofs/stage3-goal-loop-seed.md` (3 Done-Kriterien,
das dritte — "follows the project's established naming and formatting convention" —
ist bewusst mehrdeutig → soll den `escalate`-Pfad auslösen).

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
$env:DUAL_BRIDGE_ENDPOINT = 'codex@laptop-a'    # A baut = codex
python loop_driver.py --mode goal-loop `
  --repo https://github.com/dynamic-dome/dual-bridge `
  --base-branch main `
  --max-rounds 4 `
  --round-timeout 600 `
  --seed (Get-Content -Raw ..\docs\live-proofs\stage3-goal-loop-seed.md)
```

Erwartung:
- Runde 0–1: codex baut `greet()` auf `bridge/loop-<id>` → B prüft Diff gegen Kriterien,
  hakt Kriterium 1+2 ab, lehnt evtl. wegen Kriterium 3 ab (`rejected`, echter Gap).
- Spätestens wenn nur noch das mehrdeutige Kriterium 3 offen ist: `VERDICT: escalate`
  → `ESCALATION-<loop-id>.md` geschrieben, **Exit-Code 3**.

## Schritt 3 — A: Ground-Truth verifizieren (P007 — NICHT dem Status glauben)

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
# 1) Eskalations-Datei real lesen:
Get-Content (Get-ChildItem state\ESCALATION-*.md | Select -Last 1)
#    → trigger korrekt? offene Frage zum Kriterium 3 sinnvoll? Branch/Commit genannt?
# 2) Reviewer-Result real lesen (echter VERDICT-Marker, B-Device-Claim):
#    Results von B liegen in der A-to-B-Lane (_processed/) im Drive-Sharepoint:
#    G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge\lane-A-to-B\inbox\
#    bzw. ...\_processed\result-*.md — die letzte result-*.md mit kind:review ansehen.
# 3) Branch-Inhalt byte-genau gegen Remote:
git fetch origin
git show origin/bridge/loop-<id>:greet_util.py
```

Prüfe: greet() existiert byte-genau, VERDICT:-Marker echt in B's Text, B-Device
(K472HEXXZACKBUU), Eskalation am mehrdeutigen Kriterium (nicht an 1/2).

## Schritt 4 — A: Reseed-Resume bis accepted

Das mehrdeutige Kriterium schärfen (z.B. "snake_case function name, f-string greeting,
double-quoted") in einem neuen Seed `stage3-goal-loop-seed-v2.md`, dann:

```powershell
python loop_driver.py --mode goal-loop `
  --repo https://github.com/dynamic-dome/dual-bridge `
  --resume <loop-id> `
  --max-rounds 4 --round-timeout 600 `
  --seed (Get-Content -Raw ..\docs\live-proofs\stage3-goal-loop-seed-v2.md)
```

Erwartung: codex baut auf **demselben** `bridge/loop-<id>` weiter (Continuity), das
geschärfte Kriterium ist jetzt objektiv erfüllbar → `VERDICT: accepted` → **Exit 0**.
Damit sind beide Pfade (Fortschritt + Eskalation) UND Reseed-Resume bewiesen.

> Resume-Regel-Check nebenbei: ein `--resume <id>` OHNE geänderten Seed muss bei
> trigger `reviewer_requested` mit "resume abgelehnt" (Exit 2) scheitern — nur
> `max_rounds`-Eskalationen dürfen unverändert resumen.

## Aufräumen
Wegwerf-Loop-Branches `bridge/loop-...` auf dem Remote nach dem Beweis löschen
(wie bei Stufe 1/2 — NICHT mergen, `greet_util.py` ist nur Beweis-Material).
