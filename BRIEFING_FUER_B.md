# Briefing für Laptop B — HTTP-Bridge-Job

> Geschrieben von Claude Code auf **Laptop A** am 2026-06-04 für den Agenten auf **Laptop B**.
> A orchestriert den DCO (Job-Quelle), B ist der dual-bridge-Worker (Job-Verarbeiter).

## 🔎 OFFENER PUNKT (2026-06-04, neuester Stand): codex-Stagnation in Runde 0

Die **HTTP-Bridge funktioniert vollständig** — du hast 2× echte Builds gefahren
(764s / 771s), claim→build→rc→publish lief sauber, der DCO mappte rc 3 korrekt
auf `waiting_approval`/`escalated`. **ABER:** beide trivialen Tasks (Datei anlegen)
eskalierten mit `stagnation`, **Runden: 0/4** — codex schloss KEINE einzige Runde
erfolgreich ab.

Im Loop-Code (`loop_driver.py:591`) heißt `Runden: 0/4` + sofortige Stagnation:
**`out["status"] != "done"` schon in Runde 0** — also der **codex-Runner selbst**
gab kein erfolgreiches Build-Ergebnis zurück (NICHT „Reviewer rejected", NICHT
„gleicher Commit"). Der genaue Grund steht im `abort_reason` der ESCALATION-Datei.

### DIAGNOSE-AUFTRAG für B (bitte der Reihe nach)

**1. ESCALATION-Datei lesen** (sie nennt den `abort_reason`):
```powershell
cd C:\Users\domes\AI\dual-bridge
# Pfad steht im Job-payload: ESCALATION-loop-20260604-081941-459775-0-913e.md
Get-ChildItem -Recurse -Filter "ESCALATION-loop-20260604-08*.md" | Select FullName
# dann die neueste anzeigen:
Get-Content (Get-ChildItem -Recurse -Filter "ESCALATION-loop-20260604-08*.md" | Sort LastWriteTime | Select -Last 1).FullName
```
→ Poste den `reason:`/`abort_reason`-Teil. DAS ist der Kern.

**2. codex-Session-Log prüfen** (lief codex überhaupt, oder hing/crashte er?):
```powershell
# Neuestes codex-Rollout-Log:
$log = Get-ChildItem "$env:USERPROFILE\.codex\sessions" -Recurse -Filter "rollout-*.jsonl" | Sort LastWriteTime | Select -Last 1
$log.FullName
Get-Content $log.FullName -Tail 30
```
→ Der LETZTE `function_call` OHNE zugehöriges `function_call_output` = Hängepunkt.
   Bekannte Falle: **codex-0.136-exec-Hang** (CLAUDE.md §10.10) — `%TEMP%`-Sandbox +
   ererbter SessionStart-Hook. Falls du Setup-Errors `WinError 5` / `%TEMP%`-Probing
   siehst → das ist es.

**3. Branch-Zustand prüfen** (hat codex committet/gepusht?):
```powershell
# Im throwaway-Workdir des Loops (state/work/loop-...):
Get-ChildItem -Recurse -Directory -Filter "loop-20260604-08*" scripts\state\work 2>$null | Select -Last 1
# Dann darin: git log --oneline -5  und  git status
# ODER direkt am Remote schauen, ob ein loop-Branch mit Commit existiert:
git ls-remote https://github.com/dynamic-dome/test-repo "refs/heads/*loop*"
```
→ Wenn KEIN loop-Branch / kein Commit am Remote: codex hat nichts gebaut
   (Adapter-/codex-Problem). Wenn ein Commit DA ist, aber der Loop ihn nicht sah:
   Loop-Erkennungs-Bug (`_commits_ahead_of_base`, bekanntes Thema).

**Melde A:** (1) den ESCALATION-`reason`, (2) ob codex im rollout-Log normal endete
oder hing, (3) ob am Remote/Workdir ein loop-Commit existiert. Damit ist
„codex baut nichts" vs. „Loop erkennt Build nicht" eindeutig getrennt.

---

## ✅ ROOT CAUSE (Seed-Format) GEFUNDEN + GEFIXT (2026-06-04)

Der ~5s-Fail war **NICHT** codex-PATH (alte Hypothese unten, jetzt zweitrangig).
Die echte Ursache, live über den DCO-`result_payload` gefunden:

```
[A] ungueltiger Seed: seed has no '## Ziel' block
```

`loop_driver.parse_seed` verlangt einen strukturierten Markdown-Seed (`## Ziel` +
`## Done-Kriterien`), aber der DCO-Job liefert rohen Fließtext → jeder Build brach
sofort ab. **Gefixt in `job_poll.ensure_seed_structure()`** (Commit `1f3d06b`):
der rohe Seed wird automatisch ins erwartete Format gewrappt. Gegen den echten
`loop_driver.parse_seed` verifiziert.

### Was B JETZT tun soll (kurz)

```powershell
cd C:\Users\domes\AI\dual-bridge
git pull                            # MUSS 1f3d06b holen
git log -1 --format="%h %s"         # bestätigen: 1f3d06b fix(jobpoll): ... Seed ... wrappen
# Alten --watch-Worker beenden (Ctrl-C im Fenster), falls noch einer läuft.
# Env prüfen (Schritt 1 unten). Dann EIN echter Lauf:
cd scripts
python -X utf8 .\job_poll.py --once
```
Ein frischer Job liegt in der DCO-Queue (A legt ihn an). Mit dem Fix sollte codex
jetzt WIRKLICH bauen (dauert Minuten, kein 5s-Abbruch). Erwartung: rc 0 → der Job
geht im DCO auf `completed`, und im Repo `dynamic-dome/test-repo` entsteht ein
Loop-Branch mit der Datei `BRIDGE_LIVE_PROOF.md`.

**Melde A zurück:** lief der `--once` durch (codex baute Minuten lang)? Welcher
rc? Falls wieder ein Fehler: die `[job_poll] ...`-Zeile + den DCO-Job-Status.

---

## (Historisch) Ursprüngliche Diagnose-Schritte — nur falls der Fix NICHT reicht

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
