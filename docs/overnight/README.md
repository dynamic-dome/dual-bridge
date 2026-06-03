# Overnight-Queue

Dieses Verzeichnis ist die **Seed-Queue** für den Overnight-Scheduler
(`scripts/bridge_overnight.py`). Jede `*.md` hier ist ein goal-loop-Seed, der
nachts autonom abgearbeitet wird.

## Format

Identisch zum manuellen goal-loop-Seed (siehe
`docs/live-proofs/stage3-goal-loop-seed.md`):

```markdown
## Ziel
<ein klar formuliertes, abnehmbares Ziel>

## Done-Kriterien
- <objektiv prüfbares Kriterium 1>
- <objektiv prüfbares Kriterium 2>
```

## Regeln

- **Reihenfolge:** alphabetisch nach Dateiname. Steuere sie über Prefixe wie
  `01-…`, `02-…`.
- **Deaktivieren ohne Löschen:** Suffix `.skip` anhängen (`03-foo.md.skip`) oder
  die Datei nach `_done/` verschieben — beides wird ignoriert.
- **Nur oberste Ebene** zählt; Unterordner (insb. `_done/`) werden übersprungen.

## Trockenlauf

```bash
python scripts/bridge_overnight.py --dry-run \
  --repo https://github.com/dynamic-dome/dual-bridge
```

Listet die geplanten Seeds, startet aber keinen Loop und schreibt/sendet nichts.

## Aktivieren (Windows, täglich 02:00)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_overnight.ps1 `
  -Repo https://github.com/dynamic-dome/dual-bridge
```

Ergebnis: ein Morgen-Digest per Telegram (accepted / eskaliert / Fehler).
Einzelne Eskalationen meldet der separate `DualBridgeEscalationNotifier`-Task.
