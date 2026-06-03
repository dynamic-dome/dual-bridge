# State-Verzeichnis-Layout

Diese Datei beschreibt die Laufzeit-Verzeichnisse der dual-bridge, ohne dass
ein neuer Mitarbeiter zuerst den Code lesen muss. `state/` ist hier die
Kurzschreibweise fuer die operativen Bridge-Daten: die Lanes werden im Code ueber
`bridge_common.bridge_root()` / `DUAL_BRIDGE_ROOT` aufgeloest, die lokalen
Loop-Sidecars ueber `bridge_status.STATE_DIR` / `DUAL_BRIDGE_STATE` (Default:
`scripts/state/`).

## Komponenten und Schreibrechte

| Komponente | Schreibt | Liest nur |
|---|---|---|
| Poller (`handoff_poll.py`) | Receive-Lane: Claims in `outbox/`, Results in `inbox/`, archivierte Tasks in `_processed/`, Quarantaene in lane-lokalem `_errors/` | Receive-Lane-Tasks und vorhandene Results |
| `loop_driver.py` | Send-Lane-Tasks, `LOOP-*.jsonl`, `ESCALATION-*.md`, `state/work/<loop_id>/`; beim Resume auch `state/_processed/ESCALATION-*.md` | Send-Lane-Results, `ESCALATION-*.md` fuer Resume |
| `bridge_status.py` | nichts | Lanes, lane-lokale `_errors/`, `LOOP-*.jsonl`, `ESCALATION-*.md`, Poller-Lock |
| `bridge_notify.py` | `state/_notify/sent.json` | offene `ESCALATION-*.md` und Status-Digest-Daten |
| `bridge_overnight.py` | `state/_overnight/runs/*.json` und indirekt ueber gestartete `loop_driver`-Laeufe | `docs/overnight/*.md` Seeds |

## Verzeichnisse

### `state/lane-A-to-B/`

Richtung von `claude@laptop-a` nach `codex@laptop-b`: der Sender schreibt
`task-*.md` nach `outbox/`, der B-Poller claimt sie dort und schreibt
`result-*.md` in dieselbe Lane unter `inbox/`. Abgearbeitete Task- und
Result-Dateien landen in `_processed/`; `bridge_status.py` liest diese Lane nur.

### `state/lane-B-to-A/`

Richtung von `codex@laptop-b` nach `claude@laptop-a`: analog zur Gegenrichtung,
nur mit vertauschten Rollen. Der B-Knoten schreibt Tasks in `outbox/`, der
A-Poller verarbeitet sie, schreibt Results in `inbox/` und archiviert danach in
`_processed/`.

### `state/_errors/` (Quarantaene)

Es gibt im Code kein globales Top-Level-Verzeichnis `state/_errors/`; die
Quarantaene ist lane-lokal als `state/lane-A-to-B/_errors/` bzw.
`state/lane-B-to-A/_errors/` umgesetzt. Der Poller legt diese Verzeichnisse lazy
an, wenn ein malformed/hostile stranded claim gefunden wird; `bridge_status.py`
zaehlt und rendert sie prominent, schreibt aber nichts hinein.

### `state/_notify/`

`bridge_notify.py` nutzt dieses eigene Sidecar ausschliesslich fuer
`sent.json`, damit jede offene Eskalation nur einmal gemeldet wird. Der Notifier
liest `state/ESCALATION-*.md`, mutiert aber weder Eskalationsdateien noch Lanes;
bei `--reconcile` bereinigt er nur veraltete Eintraege in `sent.json`.

### `state/_overnight/runs/`

`bridge_overnight.py` schreibt pro Batch-Lauf genau einen JSON-Record nach
`state/_overnight/runs/<UTC>.json`. Die eigentlichen Loop-Artefakte
(`LOOP-*.jsonl`, `ESCALATION-*.md`, Branches und Workdirs) erzeugt weiterhin der
gestartete `loop_driver.py`.

### `state/work/<loop_id>/`

`loop_driver.py` uebergibt `state/work` als Workroot an den Codex-Runner und
setzt `workdir_name` auf die stabile `loop_id`, damit mehrere Runden denselben
Repo-Checkout wiederverwenden. Der Codex-Adapter klont bzw. fetched das Repo in
`state/work/<loop_id>/`, checkt den Loop-Branch aus und committed/pusht von dort.

## Code-Belege

- Lanes und lane-lokales `_errors/`: `scripts/bridge_common.py`
  (`lane_root`, `lane_outbox`, `lane_inbox`, `lane_processed`, `lane_errors`).
- Dashboard-Leseverhalten: `scripts/bridge_status.py` (`STATE_DIR`,
  `scan_lane`, `scan_loops`, `scan_escalations`, `_errors/`-Rendering).
- Notifier-Sidecar: `scripts/bridge_notify.py` (`NOTIFY_DIR_NAME`,
  `SENT_FILE_NAME`, `_save_sent`, `notify_new_escalations`, `reconcile`).
- Overnight-Sidecar: `scripts/bridge_overnight.py` (`OVERNIGHT_DIR_NAME`,
  `RUNS_DIR_NAME`, `_write_run_record`, `run_overnight`).
- Loop-Workdirs: `scripts/loop_driver.py` (`STATE_DIR / "work"`) und
  `scripts/codex_adapter.py` (`workroot`, `workdir_name`).
