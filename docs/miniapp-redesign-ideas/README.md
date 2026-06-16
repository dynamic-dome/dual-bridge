# Miniapp-UI-Redesign — Ideen-Queue

> **Status (2026-06-16):** Dieser rein ästhetische Loop wurde nach 13 Direktionen
> gestoppt und auf Informationsarchitektur umgeschwenkt → siehe
> `../miniapp-ia-ideas/`. Die 001–013 hier bleiben als Ästhetik-Direktionen-Archiv gültig.


Generator-Ordner: alle ~5 Minuten entstehen hier **2 neue, distinctive
Redesign-Ideen** für die DCO-Miniapp („Claude Zentrale"), jede als
ausführbarer **Bridge-Task** (goal-loop-/relay-Seed) formuliert.

## Subject (Ground Truth — wogegen designt wird)
- **Produkt:** Telegram-Mini-App, mobiles Command-Center für den Dynamic
  Central Orchestrator (Jobs, Inbox, Approvals, Artefakte, Kalender, Todos),
  steuert den Dual-Laptop-Bridge-Betrieb (codex@laptop-b ↔ claude@laptop-a).
- **Code:** `dynamic_central_orchestrator/miniapp/` — `index.html`,
  `css/tokens.css` (Design-Tokens, Source of Truth), `css/base|components|motion|style.css`.
- **Ist-Ästhetik:** „Organic Obsidian Glow" — dunkles Obsidian + bio-lumineszentes
  Cyan `#3DFFE7`, Profil-Farben (haiku/sonnet/opus), Fraunces/Geist/JetBrains Mono,
  Gradient-Mesh + Grain. Liegt nah am KI-Default *near-black + ein Acid-Accent* →
  Redesigns ziehen bewusst weg davon.

## Format jeder Idee
Jede Datei ist ein gültiger Bridge-Task (goal-loop/relay-Seed) PLUS ein
frontend-design-Token-System:

```
## Ziel                 — Thesis der Direktion (ein Absatz)
## Design-Direktion     — Palette (4–6 Hex), Typo (display/body/utility),
                          Layout (+ASCII-Wireframe), Signature
## Done-Kriterien       — objektiv prüfbar, referenziert echte Dateien
## Leitplanken          — mobile-first (Telegram), a11y-Floor, reduced-motion
## Herkunft             — Zyklus, Datum, Begründung
```

Ausführen (Beispiel, Repo = DCO):
`python loop_driver.py --mode relay-loop --repo <dco-url> --seed docs/miniapp-redesign-ideas/<datei>.md`

## Anti-Default-Disziplin
Jede Idee meidet die drei KI-Default-Looks: (1) Cream + Editorial-Serif +
Terracotta-Accent, (2) near-black + ein Acid-Accent, (3) Broadsheet-Hairlines.
Wo eine Idee eine Default-Farbe nutzt, muss sie aus der **Subjekt-Materialität**
kommen (z. B. eine Tartan-Bahn IST rostrot), nicht aus dem Default-Reflex.

## Bereits vergebene Direktionen (keine Wiederholung)
Jeder Zyklus liest diese Tabelle und wählt **frische** Direktionen.

| # | Direktion | Kern-Metapher | Datum |
|---|-----------|---------------|-------|
| 001 | Staffellauf / Track-Lane | relay-loop = Staffel, codex↔claude reichen den Stab | 2026-06-16 |
| 002 | Mission Control / Flight-Strips | Orchestrator = Tower, Jobs = Flight-Strips, Radar-Sweep | 2026-06-16 |
| 003 | Eurorack-Patchbay | Subsysteme = Module, Job = Patchkabel, Bridge = Kabel zwischen 2 Racks | 2026-06-16 |
| 004 | Transit-Liniennetzplan | Routing zwischen 2 Endpunkten = Linie A↔B, Job = fahrender Zug-Punkt | 2026-06-16 |
| 005 | Shortwave-Relaisstation | Dual-Laptop = Funk-Relais, Job = Sendung+QSL, S-Meter-Nadel | 2026-06-16 |
| 006 | Risograph-Duotone | 2 Maschinen = 2 Spot-Platten (Pink/Teal), Handoff = Passer-Deckung | 2026-06-16 |
| 007 | Sortier-Depot | Bridge = Zustelldienst, Job = Paket+Postmark, 2 Depots A/B | 2026-06-16 |
| 008 | Admiralty-Seekarte | Routing = Kurs über Wasser A↔B, Soundings, Kurslinie+Anker | 2026-06-16 |
| 009 | Observatorium / Nacht-Sternkarte | Overnight-Loop = Nacht, Job = Meridian-Durchgang, Ephemeride+Dämmerung | 2026-06-16 |
| 010 | Jacquard-Webstuhl | Lochkarte = Job-Spec (Ur-Programm), fertige Jobs weben Tuch-Reihen | 2026-06-16 |
| 011 | Sicherheits-Schleuse / Airlock | Risk-Policy 3 Gates (read/build/ops) fail-closed = Schott-Sequenz + Ampeln | 2026-06-16 |
| 012 | Gewächshaus / Glaspalast | „Seed" = echte Vokabel; Job = Pflanze (Saat→Blüte), Overnight = Ernte | 2026-06-16 |
