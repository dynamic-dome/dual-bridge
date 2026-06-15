# Capabilities

## Superpowers-Skill-Export: dual-bridge-two-model-review

- `docs/superpowers/skills/dual-bridge-two-model-review/SKILL.md` exportiert
  das dual-bridge Verifier/Builder-Pattern als wiederverwendbaren
  Superpowers-Skill.
- Der Skill beschreibt die Zwei-Modell-Rollenmatrix (`codex`/`claude`,
  `claude-build`/`codex-review`) und die Wiederverwendung ueber `goal-loop` und
  `relay-loop`.
- Der Skill haelt den Doku-DoD fuer diesen Export fest: Aenderungen werden in
  `docs/CHANGELOG.md` und `docs/CAPABILITIES.md` dokumentiert, nicht in einem
  Root-CHANGELOG.

## Status-Dashboard

- `scripts/bridge_status.py` rendert einen read-only Snapshot der Bridge als Text
  oder JSON.
- Die Text-Ansicht zeigt vertikale Knoten-Tabs fuer Laptop A und Laptop B mit
  Modell, aktiver Empfangs-Lane und Zustandsindikator.
- Knotenstatus: `red` = attention needed bei Dateien in `_errors/`, `green` =
  offene oder geclaimte Arbeit auf der aktiven Lane, `gray` = idle.
- Die JSON-Ausgabe enthaelt dieselben Knoten-Metadaten unter `node_tabs`.
