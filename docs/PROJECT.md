# Project - dual-bridge

## Kurzbeschreibung

`dual-bridge` ist eine dateibasierte, bidirektionale Handoff-Bridge zwischen
zwei lokalen Agenten-Endpunkten. Aufgaben, Ergebnisse, Reviews und Loop-
Artefakte werden ueber den Google-Drive-Sharepoint synchronisiert; die
ausfuehrenden Skripte und Repos bleiben lokal.

## Zweck

Das Projekt soll agentische Arbeit zwischen Maschinen und Modellen robust
uebergeben: ein Endpoint schreibt einen Auftrag, der andere claimt ihn,
arbeitet ihn mit dem passenden Adapter ab und liefert ein Ergebnis zurueck.
Darauf baut der Goal-Loop auf: bauen, reviewen, bei Bedarf eskalieren oder
akzeptieren.

## Aktueller Stand

- Stage 2a: modulare Lane-/Adapter-/Endpoint-Architektur ist gebaut.
- Stage 3: Goal-Loop mit Owner-Eskalation ist live und cross-device bewiesen.
- Read-only Status-Dashboard, Eskalations-Notifier und Overnight-Scheduler sind
  vorhanden.
- DCO-Anbindung und HTTP-Job-Pull sind vorbereitet/skizziert, aber noch nicht
  verdrahtet.
- Scheduled Tasks fuer Overnight/Notifier sind als naechster operativer Schritt
  vorgesehen und duerfen nur nach Dry-Run aktiviert werden.

## Architektur in einem Absatz

Zwei richtungsgetrennte Lanes (`lane-A-to-B`, `lane-B-to-A`) enthalten je
`outbox/`, `inbox/`, `_processed/` und `_errors/`. Ein Endpoint schreibt in die
Sende-Lane und pollt die Empfangs-Lane. Atomarer Claim erfolgt dateibasiert;
ungueltige Tasks werden quarantined, geclaimte Tasks koennen bei Crash requeued
werden. Adapter (`echo`, `codex`, `claude`) trennen Fachabsicht von ausfuehrendem
Modell.

## Kernfaehigkeiten

- Cross-device Handoff A->B und B->A.
- Adapter-Dispatch fuer Echo-Smokes, Codex-Implementierungen und Claude-Textjobs.
- Goal-Loop mit Build-/Review-Runden, Resume und Eskalationsdateien.
- Overnight-Seed-Queue unter `docs/overnight/`.
- Telegram-Digest/Eskalationsbenachrichtigung ueber `bridge_notify.py`.
- Read-only Maschinenstatus ueber `bridge_status.py`.

## Wichtige Einstiege

- `HOW-TO-USE.md` - Bedienindex fuer User und Agenten.
- `README.md` - Vollreferenz fuer Architektur, Protokoll und Env-Vars.
- `CLAUDE.md` - agentische Laufzeitregeln und konkrete Startbefehle.
- `docs/CHANGELOG.md` - chronologischer Aenderungsverlauf.
- `docs/superpowers/specs/` - Design-Specs.
- `docs/superpowers/plans/` - Implementierungsplaene.

## Tech Stack

- Python-Skripte und pytest-basierte Tests.
- Git/GitHub fuer Branches, Commits und Live-Proofs.
- Google Drive Sharepoint als Datentransport.
- Windows Scheduled Tasks fuer optionale lokale Trigger.
- Telegram-Notifier fuer Eskalationen und Overnight-Digests.

## Grenzen

- Der Sharepoint traegt Daten, keinen Code.
- Tasks duerfen keine Secrets enthalten.
- Tests duerfen nie gegen den echten Sharepoint oder produktive State-Pfade
  laufen.
- DCO ist noch kein nativer Producer fuer Bridge-Jobs.
- HTTP-Job-Pull ist eine Skizze, kein aktiver Transport.

## Naechste sinnvolle Schritte

1. Overnight- und Notifier-Scheduled-Tasks nach Dry-Run aktivieren.
2. DCO-Queue-Anbindung als eigenen Spec-/Plan-Slice ausarbeiten.
3. HTTP-Job-Pull nur dann ausbauen, wenn Drive-Latenz oder N-Worker-Skalierung
   real zum Problem wird.
