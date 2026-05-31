# HOW-TO-USE — Dual-Laptop-Bridge

Wegweiser für **User UND Agent**. Vollreferenz steht im [README](README.md);
diese Datei ist nur der Index: *was ist das, wo liegt was, wie startet man*.

## Was ist dieses Projekt

Dateibasierte, **bidirektionale** Handoff-Bridge zwischen zwei Laptops über den
Google-Drive-Sharepoint. Jeder Knoten kann senden und empfangen; welcher Knoten
welches Modell fährt (Claude / Codex / Echo) und welche Richtung er bedient, ist
reine Konfiguration (`DUAL_BRIDGE_ENDPOINT`). Aktueller Ausbau: **Stage 2a**
(Lanes + Adapter + endpoint-relative Skripte).

## Wo liegt was

| Pfad | Inhalt |
|---|---|
| `scripts/` | Die 4 Skripte + Adapter + `bridge_common.py` + Tests |
| `scripts/handoff_write.py` | Task schreiben |
| `scripts/handoff_poll.py` | Pollen + verarbeiten (Empfänger) |
| `scripts/handoff_collect.py` | Results einsammeln (Sender) |
| `scripts/latency_probe.py` | Roundtrip-Latenz messen |
| `README.md` | Vollreferenz: Architektur, Env-Vars, Task-Protokoll |
| `docs/superpowers/specs/2026-05-31-dual-bridge-stage2a-modulare-v2-design.md` | Design-Spec |
| `docs/superpowers/plans/2026-05-31-dual-bridge-stage2a-modulare-v2.md` | Umsetzungs-Plan |
| `~/wiki/wiki/plans/2026-05-30-dual-bridge-master-plan.md` | Master-Plan (alle Stufen) |

## Als User starten (die 3 Befehle)

Alle Skripte laufen auf **beiden** Knoten identisch — Richtung nur per
`DUAL_BRIDGE_ENDPOINT` (Default `claude@laptop-a`).

```bash
cd ~/AI/dual-bridge/scripts
python handoff_write.py --adapter codex --kind implement --repo <url> "Auftrag"
python handoff_collect.py --watch     # auf der Sender-Seite: wartet aufs Result
python handoff_poll.py --watch        # auf der Empfänger-Seite: verarbeitet Tasks
```

Auf Laptop B vorher Endpoint setzen:
`export DUAL_BRIDGE_ENDPOINT=codex@laptop-b`
(PowerShell: `$env:DUAL_BRIDGE_ENDPOINT="codex@laptop-b"`).

## Als Agent starten

1. **Spec + Plan lesen:** `docs/superpowers/specs/...stage2a...-design.md` und
   `docs/superpowers/plans/...stage2a...md` — sie definieren das Lane-/Adapter-/
   Endpoint-Modell.
2. **Tests laufen lassen** (Ground Truth vor Änderungen):
   `cd ~/AI/dual-bridge/scripts && python -m pytest`
   — erwartet 42 grün (`test_lanes` 11, `test_claude_adapter` 4,
   `test_hardening` 10, `test_stage1` 17).
3. Erst dann ändern. README ist die Detailreferenz.

## Aktueller Stand

- ✅ **Stage 2a fertig:** Lanes, Adapter, Bidirektionalität, endpoint-relative
  CLI. B→A-Roundtrip config-only bewiesen, 42 Tests grün.
- ⬜ **Offen:** Live-`claude -p`-Beweis geräteübergreifend über die echte Bridge.
- ⬜ **Stage 2b:** Review-Loop (`kind: review`) + Overnight-Scheduler — noch nicht begonnen.

## Wichtigste Env-Vars

| Variable | Zweck | Default |
|---|---|---|
| `DUAL_BRIDGE_ENDPOINT` | Wer bin ich (`claude@laptop-a` / `codex@laptop-b`) | `claude@laptop-a` |
| `DUAL_BRIDGE_ROOT` | Bridge-Ordner (falls Drive-Pfad auf B abweicht) | Sharepoint-Pfad |
| `DUAL_BRIDGE_WORKROOT` | Arbeitsverzeichnis für codex/claude-Runner | `~/dual-bridge-work` |
| `DUAL_BRIDGE_REPO_ALLOWLIST` | codex-Repo-Allowlist (fnmatch, Komma-getrennt) | leer = alle |

Vollständige Env-Var-Tabelle: [README → Konfiguration](README.md#konfiguration-env-vars).
