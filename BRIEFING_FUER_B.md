# Briefing für Laptop B — Diagnose: warum failt der HTTP-Bridge-Job in ~5 s?

> Geschrieben von Claude Code auf **Laptop A** am 2026-06-04 für den Agenten auf **Laptop B**.
> A orchestriert den DCO (Job-Quelle), B ist der dual-bridge-Worker (Job-Verarbeiter).
> Lies das ganze Dokument, dann arbeite die Diagnose-Schritte der Reihe nach ab.

## Kontext in 3 Sätzen

Der DCO (auf A, erreichbar über `https://bot.dynamic-dome.com/api`) hat eine
Job-Queue. Der neue HTTP-Worker `scripts/job_poll.py` (auf B) soll Jobs ziehen,
sie über `loop_driver.py --mode goal-loop` (echter **codex**-Build) abarbeiten und
das Ergebnis zurückmelden. **Problem:** Jeder echte Job schlägt nach **~5 Sekunden**
mit `failed/error` fehl — viel zu schnell für einen echten codex-Build. Verdacht:
`run_fn` (= codex-Subprozess) crasht sofort, bevor codex überhaupt arbeitet.

## Ground Truth von der DCO-Seite (A hat das gemessen)

3 dual-bridge-Jobs bisher:
- `93aee1b3aed8` → **completed** (9.9s) — war ein Fake-run_fn-Smoke (kein echter Build), beweist nur Transport.
- `733df07cd787` → **failed/error** (4.7s) — echter Build-Versuch, sofort tot.
- `6a2288c293ca` → **failed/error** (5.7s) — echter Build-Versuch, sofort tot.

Die beiden `failed` haben `result_payload=None` — die Fehlerursache wurde NICHT
zurückgemeldet. **Grund:** der Worker, der sie verarbeitet hat, lief noch mit altem
Code (vor dem Fix `c3eae1c`, der den run_fn-Output als `result_payload` mitschickt).

## SCHRITT 0 — Code-Stand & laufende Prozesse prüfen (zuerst!)

```powershell
cd C:\Users\domes\AI\dual-bridge   # oder wo das Repo auf B liegt
git log -1 --format="%h %s"        # MUSS c3eae1c sein, sonst:
git pull                            # holt den payload-Fix
```

**Läuft noch ein alter `--watch`-Worker?** Der schnappt sich jeden Job sofort mit
altem Code. Such ihn und beende ihn:
```powershell
Get-Process python* | Format-Table Id, ProcessName, StartTime, Path
# Wenn ein job_poll-Worker läuft: das PowerShell-Fenster mit Ctrl-C beenden,
# oder gezielt: Stop-Process -Id <PID>
```
Erst wenn KEIN alter Worker mehr läuft UND `git log` `c3eae1c` zeigt, weiter.

## SCHRITT 1 — Env-Variablen des Workers verifizieren

Der Worker liest diese aus `os.environ` (KEIN `.env`!). Prüfe in DERSELBEN Shell,
in der du den Worker startest:
```powershell
echo "TRANSPORT=$env:DUAL_BRIDGE_TRANSPORT"      # muss: http
echo "URL=$env:DCO_BRIDGE_URL"                    # muss: https://bot.dynamic-dome.com/api  (auf /api enden!)
echo "TOKEN=$env:DCO_BRIDGE_TOKEN"                # muss: P57_ScWim-9GMMeIUduBKBWveR2ALH05dJsJ8EtuGDE
echo "WT=$env:DUAL_BRIDGE_WORKER_TYPE"            # muss: dual-bridge (oder leer = Default)
```
Falls leer → setzen (persistent via `setx`, dann NEUE Shell öffnen):
```powershell
setx DUAL_BRIDGE_TRANSPORT   "http"
setx DCO_BRIDGE_URL          "https://bot.dynamic-dome.com/api"
setx DCO_BRIDGE_TOKEN        "P57_ScWim-9GMMeIUduBKBWveR2ALH05dJsJ8EtuGDE"
setx DUAL_BRIDGE_WORKER_TYPE "dual-bridge"
```

## SCHRITT 2 — HAUPTVERDACHT: ist `codex` im PATH des Workers?

`scripts/codex_adapter.py:389` macht `codex_exe = codex_bin or shutil.which("codex")`.
Wenn `shutil.which("codex")` `None` liefert (codex nicht im PATH dieses Prozesses —
**klassische Windows-Subprocess-PATH-Falle**, CLAUDE.md §10.1), bricht der Build
SOFORT ab → genau die ~5 Sekunden.

```powershell
# Findet die Shell codex?
Get-Command codex -ErrorAction SilentlyContinue | Format-List Name, Source
# Findet PYTHON codex? (das ist was zählt — Worker nutzt shutil.which)
python -c "import shutil; print('codex ->', shutil.which('codex'))"
```
- Liefert das `None` oder nichts → **das ist die Ursache.** Fix-Optionen:
  (a) `setx DUAL_BRIDGE_CODEX_BIN "C:\voller\pfad\zu\codex.cmd"` (oder `.exe`) — der
      Adapter liest diese Env-Var bevorzugt (`codex_adapter.py:523`).
  (b) codex global in den PATH legen und NEUE Shell öffnen.
- **Achtung Windows:** codex ist oft ein `.cmd`-Wrapper (npm). `shutil.which("codex")`
  findet `.cmd` nur, wenn `.CMD` in `$env:PATHEXT` steht (Standard tut das).
  Wenn `DUAL_BRIDGE_CODEX_BIN` gesetzt wird, den **vollen Pfad inkl. `.cmd`-Endung** nehmen.

## SCHRITT 3 — Einen Job kontrolliert ziehen, MIT vollem Output

A legt frische Test-Jobs in die Queue (gegen das Wegwerf-Repo
`https://github.com/dynamic-dome/test-repo`). Sag A Bescheid ("leg einen frischen
Job an"), ODER prüfe ob schon einer queued ist. Dann EIN einzelner Lauf:

```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
python -X utf8 .\job_poll.py --once
```

Erwartete Ausgabe-Fälle:
- **Leere Queue:** keine Ausgabe, Prozess endet (rc 0). Heißt: kein Job da ODER ein
  anderer Worker war schneller. → mit A frischen Job anlegen lassen, alten Worker killen.
- **Job gezogen, run_fn-Crash:** Zeile `[job_poll] run_fn fehlgeschlagen für <id>: <Fehler>`
  auf stderr. **DIESE ZEILE IST DAS ZIEL** — sie nennt die echte Ursache. Kopiere sie.
- **codex baut wirklich:** dauert Minuten (kein sofortiges Ende). Dann lief es durch.

## SCHRITT 4 — Falls Schritt 3 nichts Klares zeigt: loop_driver direkt testen

Den Build-Pfad isoliert anstoßen (ohne die HTTP-Schicht), mit sichtbarem Output:
```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
python -X utf8 .\loop_driver.py --mode goal-loop `
  --repo https://github.com/dynamic-dome/test-repo `
  --base-branch main --adapter codex `
  --max-rounds 1 --round-timeout 300 `
  --seed "Lege eine Datei BRIDGE_LIVE_PROOF.md im Repo-Root an mit einer Zeile."
echo "loop_driver rc=$LASTEXITCODE"
```
Das zeigt den codex-Fehler ungefiltert. rc-Bedeutung: 0=accepted, 3=escalated,
2=config/resume-error, 1=other. Bei rc 2 sofort → fast sicher codex-Bin/Repo/Env.

## Was A braucht (zurückmelden an den A-Agenten)

1. Output von SCHRITT 0 (`git log -1`, laufende Worker ja/nein).
2. Output von SCHRITT 2 (`shutil.which('codex')` — der wichtigste Wert).
3. Die `[job_poll] run_fn fehlgeschlagen ...`-Zeile aus SCHRITT 3, ODER der
   loop_driver-Output aus SCHRITT 4.

Mit `shutil.which('codex')` + der Fehlerzeile ist die Ursache fast sicher
geklärt. Häufigster Fall (Erwartung): codex nicht im Worker-PATH → `DUAL_BRIDGE_CODEX_BIN`
setzen.

## Sicherheits-/Isolations-Hinweise

- Das Ziel-Repo `dynamic-dome/test-repo` ist ein **Wegwerf-Repo** — codex darf dort
  echt klonen/branchen/committen/pushen (eigener Loop-Branch). Kein Produktiv-Repo anfassen.
- Der DCO hat `BRIDGE_REPO_ALLOWLIST=https://github.com/dynamic-dome/*` — nur
  dynamic-dome-Repos werden als Job-Ziel akzeptiert.
- Token `P57_ScWim-...` ist das Bridge-Token; nur über Bearer-Header schicken (macht der Worker).
