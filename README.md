# Dual-Laptop-Bridge

Elementarer, dateibasierter Handoff zwischen **Laptop A** (Orchestrator) und
**Laptop B** (Worker) über den Google-Drive-Sharepoint. **Stage 0** beweist das
Fundament: A schreibt einen Auftrag, B liest ihn und antwortet, A sieht die
Antwort — noch ohne LLM, reines Echo.

> **Master-Plan (vollständige Strategie, alle 4 Stufen):**
> `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md`

## Architektur

```
LAPTOP A (Orchestrator)                      LAPTOP B (Worker)
  handoff_write.py   ──schreibt──┐     ┌──liest── handoff_poll.py
  handoff_collect.py ◄─liest──────┤     └──schreibt──────┘
                                  ▼
   G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge\
     outbox/      A→B  Tasks (task-<id>.md)
     inbox/       B→A  Results (result-<id>.md)
     _processed/  Archiv (kein Auto-Delete)
```

**Code liegt lokal** (`~/AI/dual-bridge/scripts/`), **nie im Sharepoint** —
der Sharepoint trägt nur Daten (Manifest §7). Keine Secrets in Tasks (Regel 6).
Verarbeitetes wird verschoben, nie gelöscht (Regel 7).

## Bedienung

### Auf Laptop A (Auftrag schicken + Antwort holen)

```bash
cd ~/AI/dual-bridge/scripts
python handoff_write.py "Dein Auftrag an Laptop B"
python handoff_collect.py --watch        # wartet, bis das Result da ist
```

### Auf Laptop B (Worker laufen lassen)

```bash
cd ~/AI/dual-bridge/scripts
python handoff_poll.py --watch           # pollt alle 15s, echo't jeden Task
```

Einmal-Durchlauf statt Dauerschleife: dieselben Skripte ohne `--watch`.

## Konfiguration (Env-Vars)

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ROOT` | Bridge-Ordner überschreiben (falls Drive-Pfad auf B anders ist) | `G:\Meine Ablage\...\00_INBOX\dual-bridge` |
| `DUAL_BRIDGE_DEVICE` | Geräte-Label in Claim/Result | `%COMPUTERNAME%` |

**Wichtig für Laptop B:** Prüfe zuerst, ob der Google-Drive-Mount denselben
Laufwerksbuchstaben (`G:`) hat. Falls nicht, setze `DUAL_BRIDGE_ROOT`.

## Task-Protokoll (bleibt über alle Stufen stabil)

```yaml
---
created: 2026-05-30T13:45:53
agent: laptop-a-claude@DEVICE      # Quelle
target_agent: laptop-b-worker
purpose: handoff
status: open                        # open → claimed → done → consumed
task_id: 20260530-134553-044
kind: echo                          # echo|implement|research|review|test
claimed_by:                         # B füllt beim Claim
claimed_at:
---
## Auftrag
...
## Akzeptanzkriterien
- [ ] ...
## Ergebnis
<B füllt das>
```

## Verifizierter Stand (2026-05-30)

- ✅ Voller Roundtrip A→B→A (eine Maschine, beide Rollen) — Echo korrekt zurück.
- ✅ Umlaute erhalten (UTF-8 ohne BOM).
- ✅ Leere Ordner crashen nicht.
- ✅ Doppel-Claim-Schutz (zweiter Poll verarbeitet 0).

## Nächste Schritte (siehe Master-Plan)

1. **Auf Laptop B verproben:** echten geräteübergreifenden Roundtrip + Drive-Sync-Latenz messen.
2. **Stage 1:** Echo → echter `codex exec` / `claude -p`-Aufruf (robustes Output-Parsing, siehe Wiki L17/P006).
3. **Stage 2:** Peer-Review-Loop (`kind: review`) + Overnight-Scheduler.
