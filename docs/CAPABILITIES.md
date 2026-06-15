# Capabilities

## Status-Dashboard

- `scripts/bridge_status.py` rendert einen read-only Snapshot der Bridge als Text
  oder JSON.
- Die Text-Ansicht zeigt vertikale Knoten-Tabs fuer Laptop A und Laptop B mit
  Modell, aktiver Empfangs-Lane und Zustandsindikator.
- Knotenstatus: `red` = attention needed bei Dateien in `_errors/`, `green` =
  offene oder geclaimte Arbeit auf der aktiven Lane, `gray` = idle.
- Die JSON-Ausgabe enthaelt dieselben Knoten-Metadaten unter `node_tabs`.
