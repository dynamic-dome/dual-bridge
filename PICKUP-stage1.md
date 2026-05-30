# Dual-Bridge Stage 1 — Pickup für Laptop B

Stage 1 ersetzt das Echo durch einen echten `codex exec`-Aufruf, der in einem
Git-Repo arbeitet und das Ergebnis als `bridge/task-<id>`-Branch pusht.

Verifiziert auf Laptop A gegen codex-cli 0.133: der Adapter ruft
`codex exec -C <workdir> -s workspace-write -o <antwort.txt> <prompt>`.

## 0. Voraussetzungen prüfen
```powershell
python --version                 # 3.x
codex --version                  # codex muss im PATH sein
codex exec --help | Select-String "-o|--output-last-message|-s|--sandbox|-C|--cd"
git --version
```
Erwartet: `-o/--output-last-message`, `-s/--sandbox` (mit `workspace-write`),
`-C/--cd` sind vorhanden. Wenn `codex` fehlt: installieren / in den PATH legen
(sonst liefert jeder Task `status: error` „codex nicht gefunden"). Ist die
codex-Version älter und kennt kein `-o`: der Adapter fällt automatisch auf
stdout-Parsing zurück (degradiert sauber) — im Lauf-Log vermerken.

## 1. Skripte ziehen
Aus dem Sharepoint-Pickup nach `C:\Users\domes\AI\dual-bridge\scripts\` kopieren
(alle `.py` + `register_watchdog.ps1`). Mechanik-Selbsttest:
```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
python test_stage1.py            # erwartet: Alle 17 Tests bestanden
python test_hardening.py         # erwartet: Alle 5 Tests bestanden
```
(Auf B mit echtem codex im PATH zeigt `test_task_codex_not_found` evtl. `SKIP` —
das ist OK und zählt als bestanden.)

## 2. Wegwerf-Test-Repo anlegen (lokal + Remote)
Erst gegen einen Sandkasten beweisen, NICHT gegen ein echtes Projekt.
(Remote z.B. ein leeres GitHub-Repo `dynamic-dome/bridge-sandbox`, oder ein bares
lokales Repo zum reinen Mechanik-Test. Wichtig: der `base_branch` — Default `main`
— muss im Remote existieren.)

## 3. Poller starten (Terminal, sichtbar)
```powershell
cd C:\Users\domes\AI\dual-bridge\scripts
# optional: $env:DUAL_BRIDGE_CODEX_TIMEOUT = "600"
# optional: $env:DUAL_BRIDGE_WORKROOT = "C:\Users\domes\AI\dual-bridge-work"
python handoff_poll.py --watch
```
Läuft passiv, pollt alle 15 s. Mit Strg+C beenden. Doppelstart ist durch den
Singleton-Lock unmöglich (zweiter Start beendet sich selbst mit klarer Meldung).

## 4. (A schickt einen echten Task)
Auf Laptop A:
```powershell
python handoff_write.py "Lege eine Datei hello.txt mit dem Text 'hi from B' an" `
  --kind implement --repo <test-repo-url> --base-branch main
```

## 5. Ergebnis prüfen — Ground-Truth, nicht nur status!
Auf A nach ~1-2 Sync-Zyklen (~28 s je Richtung):
```powershell
python handoff_collect.py
git fetch ; git checkout bridge/task-<id>   # den echten Branch ansehen
```
`status: done` NICHT blind glauben — den Branch wirklich auschecken und den
Commit-Inhalt prüfen (echte codex-Arbeit drin?). Erst dann ist Stage 1 bewiesen.
Einen Fehlerpfad einmal real sehen: z.B. mit absichtlich falschem `--repo` →
`status: error` im Result.

## 6. Watchdog (optional, erst nach erstem gutem Roundtrip)
```powershell
powershell -ExecutionPolicy Bypass -File register_watchdog.ps1
# Deaktivieren:
Unregister-ScheduledTask -TaskName "DualBridgePollerWatchdog" -Confirm:$false
```
Startet den Poller alle 10 min neu (überlebt Abstürze/Neustarts). Sicher, weil
der Self-Guard im Poller einen Doppelstart verhindert.

## Env-Variablen (Übersicht)
| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ROOT` | Bridge-Datenwurzel (outbox/inbox/_processed) | Drive-Pfad |
| `DUAL_BRIDGE_DEVICE` | Geräte-Label im Claim | `COMPUTERNAME` |
| `DUAL_BRIDGE_CODEX_BIN` | expliziter codex-Pfad | `shutil.which("codex")` |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für Klone | `~/dual-bridge-work` |
| `DUAL_BRIDGE_CODEX_TIMEOUT` | codex-Timeout (s) | `600` |
| `DUAL_BRIDGE_LOCK` | lokaler Lock-Pfad | Temp-Dir |
