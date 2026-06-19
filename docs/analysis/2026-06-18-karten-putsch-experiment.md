# Karten-Putsch-Experiment (Wegwerf-Notiz)

Quelle: DCO-Todo #7911 / crazy-professor kept-Run 1, Provokation #5.

Status: Experimentfenster fuer die urspruenglich genannte 1.6-Erweiterung ist
verpasst; `adapter_git.py` und die Git-Adapter-Triage sind inzwischen real
gebaut. Diese Notiz haelt die absichtlich vorweggenommene Karte trotzdem als
kleines Pattern-Artefakt fest.

## Routing-Regel

Eine neue Bridge-Erweiterung startet nicht als freier `bridge`-Todo-Seed. Sie
bekommt zuerst eine knappe Gegenwarts-Karte:

- welche Lane sie benutzt
- welcher Adapter sie ausfuehrt
- welches Artefakt spaeter beweist, dass sie wirklich existiert
- welche Operationen explizit nicht ueber die Bridge laufen duerfen

Wenn die Karte nicht in vier Zeilen passt, ist die Idee noch kein baubarer
Bridge-Task.

## Lane-Eintrag

`adapter-git` ist die Referenz-Lane fuer Git-Arbeit: lokale Worktree-Arbeit,
expliziter Branch, Commit, Push, danach Review oder Merge-Gate. Die Lane traegt
keine Owner-Entscheidung und aktiviert keine Scheduled Tasks. Ops bleibt
interaktiv.

## Pflicht-Metadaten

- `kind`: fachliche Absicht, nicht Modellname
- `adapter`: ausfuehrendes Werkzeug
- `repo`: expliziter Ziel-Checkout oder Remote
- `artefakt`: Datei, Symbol oder Testziel, das nach Merge auf der Base beweisbar ist
- `risk`: `read`, `build` oder `ops`

`risk=ops` ist kein Bridge-Job. Der Eintrag wird als Analyse oder Owner-Entscheid
festgehalten, nicht gequeued.

## Claim-Konvention

Ein Worker claimt nur Tasks, deren `kind` und `adapter` in der Risk-Policy
bekannt sind. Ein unbekanntes Feld erzeugt ein Fehlerresultat statt stiller
Interpretation. Ein accepted Resultat beweist nur den Worker-Verdiktstatus; der
Merge wird separat per Artefakt auf der Base verifiziert.

## Nutzen der Wegwerf-Karte

Die Karte zwingt eine Erweiterung in Gegenwartsform. Wenn sie falsch klingt,
bevor Code existiert, ist das ein Design-Signal. Wenn sie spaeter mit der realen
Implementierung kollidiert, markiert sie genau den Punkt, an dem die mentale
Architektur vor der Runtime driftete.
