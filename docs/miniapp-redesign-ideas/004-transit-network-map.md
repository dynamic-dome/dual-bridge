## Ziel

Gestalte die Miniapp-UI als **Nahverkehrs-Liniennetzplan**. Das Produkt routet
Arbeit zwischen zwei Endpunkten — genau das, was ein Liniennetz tut. Die Bridge
ist die zentrale Linie zwischen zwei Endstationen (laptop-a, laptop-b);
Job-Zustände sind Stationen entlang der Linie (queued → running → accepted);
ein Handoff ist ein Umstieg an einer Umsteigestation. Held des Start-Views ist
die **lebende Linie** mit einem fahrenden Zug-Punkt, der den Job in Fahrt zeigt —
keine Zahl, sondern Wayfinding. Passt zur Navigations-Natur der App.

## Design-Direktion (Token-System)

**Palette** — Nacht-Netzplan: tiefes Marineblau statt Cream (meidet den
Cream-Default), darauf kräftige U-Bahn-Linienfarben als Routen/Subsysteme:
- `--map-night:   #0E1430`  — Nacht-Netzplan-Hintergrund
- `--map-panel:   #182148`  — Panels/Cards (etwas heller als Nacht)
- `--map-ink:     #F4F6FB`  — Stationslabels, Roundel-Ringe (near-white)
- `--line-bridge: #E2433B`  — die A↔B-Bridge-Linie (rot, Hauptlinie)
- `--line-codex:  #2C9CDB`  — Route codex (blau)
- `--line-claude: #F2A33C`  — Route claude (amber)

**Typografie** — Beschilderungs-Grounding über eine Transport-Grotesk:
- Display + Body: **Overpass** — aus US-Highway-Gothic abgeleitet, Verkehrs-Signage.
- Utility/Data: **Overpass Mono** — Linien-Codes, Zeiten, Job-IDs.

**Layout** — schematisches Liniendiagramm, **nur 45°/90°-Segmente** (echte
Netzplan-Regel); die Bridge-Linie zentral mit zwei Endstations-Roundels A/B;
Stationen = Job-Zustände; Umsteigesymbole, wo Linien sich treffen (= Job-Verzweigung).
Strukturgeber: **Roundels + Umsteigesymbole**, keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⊙ live ● 1 in transit │
├──────────────────────────────────────────────┤
│  (A)━━━━●━━━━◯━━━━━━╋━━━━━◯━━━━(B)              │
│ laptop-a  queued  running │  review   laptop-b │
│                    ▲train │ ┃umstieg            │
│                           ┗━━◯ accepted (codex) │
│                                                │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — der **fahrende Zug-Punkt**: ein Punkt bewegt sich entlang der
Bridge-Linie von Station zu Station, während ein Job fortschreitet;
Umsteige-Roundels pulsieren kurz bei einem Handoff. Streng 45°/90°-Geometrie.
`prefers-reduced-motion: reduce` → Zug-Punkt springt ohne Animation zur aktuellen Station.

## Done-Kriterien

- [ ] `css/tokens.css`: Nacht-Netz-Palette + Linienfarben als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display`/`--font-body` auf Overpass, `--font-mono` auf Overpass Mono;
      Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert den **Job-Lebenszyklus als Linie mit Stations-
      Roundels** (SVG, nur 45°/90°-Segmente) und zwei Endstations-Roundels A/B.
- [ ] Der **Zug-Punkt** bewegt sich entlang der Linie passend zum Job-Status;
      Handoff/accepted → Umsteige-Roundel-Puls.
- [ ] Linienfarben mappen eindeutig auf Routen (bridge/codex/claude).
- [ ] Kontrast map-ink/map-night ≥ 4.5:1; sichtbarer Tastatur-Fokus; responsiv
      bis 360px (Diagramm vertikal kippbar), keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Zug-Punkt); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 2, 2026-06-16. Direktion gewählt, weil „Arbeit
zwischen zwei Endpunkten routen" sich 1:1 auf ein Liniennetz abbildet, die
45°/90°-Regel ein echtes Struktur-Constraint liefert und der fahrende Zug-Punkt
den Job-Fortschritt als Wayfinding erzählt — Nacht-Marineblau statt Cream-Default.
