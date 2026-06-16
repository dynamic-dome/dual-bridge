## Ziel

Gestalte die Miniapp-UI als **Tower / Mission Control mit Flight-Strips**. Ein
Orchestrator, der Jobs zwischen zwei Maschinen routet, ist ein Fluglotse, der
Flüge zwischen zwei Pisten (laptop-a / laptop-b) sequenziert. Job-Zustände werden
zu Flugphasen: queued = HOLDING, running = ACTIVE/on approach, accepted = CLEARED,
escalated = GO-AROUND. Echtes Lotsen-Artefakt: der **Flight Progress Strip** — ein
schmaler, dichter, gefelderter Streifen pro Flug, der physisch über ein Board in
seine Phasen-Bucht geschoben wird. Held des Start-/Aktivität-Views ist das
**Strip-Board** mit einem langsamen Radar-Sweep dahinter, keine große Zahl.

## Design-Direktion (Token-System)

**Palette** — Duotone-Spannung: kühles Leitstand-Phosphor gegen warme
Papier-Strips. Das hält es bewusst weg vom Default *near-black + ein Acid-Accent*
(hier ein deliberater Dreiklang Phosphor/Amber + Papier-Layer):
- `--console:     #0B1410`  — Leitstand-Grünschwarz, Board-Hintergrund
- `--phosphor:    #4BE08A`  — Radar/Phosphor-Grün, sparsam für Sweep + Live-Daten
- `--amber-strip: #E8B23A`  — Amber-CRT, für Alerts/Approvals (GO-AROUND)
- `--strip-paper: #E7E2D2`  — der physische Flight-Strip, warme Off-White-Card
- `--strip-ink:   #14110B`  — Strip-Text
- `--runway-blue: #5BA6C9`  — Taxi-/Routelinien zwischen Buchten

**Typografie** — Subjekt-Grounding über eine echte Luftfahrt-Typo:
- Display + Body: **B612** — von Airbus für Cockpit-Lesbarkeit entworfen.
- Utility/Data: **B612 Mono** — die Strip-Felder sind ein Monospace-Raster
  (Callsign, Squawk, Zeit, Route).

**Layout** — horizontale Strip-Zeilen in beschrifteten Buchten
(HOLDING / ACTIVE / CLEARED / GO-AROUND). Strukturgeber: **Bucht-Labels** + ein
langsamer Radar-Sweep. Keine 01/02-Nummerierung (Zustände sind keine vom Nutzer
gezählte Sequenz) — stattdessen **4-stellige Squawk-Codes** als Job-IDs (echtes
Lotsen-Vokabular).
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⌖ radar ● sweeping    │
├──────────────────────────────────────────────┤
│ ── ACTIVE ───────────────────────── A↔B ──     │
│ │7831│ codex   │ implement  │ 04:12 │ →CLR │   │ ← strip (paper card)
│ ── HOLDING ────────────────────────────────    │
│ │2204│ claude  │ review     │ --:-- │ wait │   │
│ ── GO-AROUND ──────────────────────── ! ──     │
│ │6600│ codex   │ escalated  │ 12:39 │ OWNR │   │ ← amber strip
│                                                │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — der **Radar-Sweep**: eine einzige langsam rotierende Sweep-Linie
hinter dem Board, die einen Strip kurz illuminiert, wenn sie ihn überstreicht;
hat der Strip ein Update, „pingt" er beim Überstreichen kurz auf. Genau eine
ambiente Bewegung, alles andere steht still.

## Done-Kriterien

- [ ] `css/tokens.css`: Duotone-Palette als benannte Tokens; Legacy-Mapping
      (`--bg`, `--accent`, …) konsistent neu verdrahtet, ohne bestehende Styles
      zu brechen.
- [ ] `--font-display`/`--font-body` auf B612, `--font-mono` auf B612 Mono;
      Fonts lokal als woff2 eingebunden (Preload analog `index.html`).
- [ ] Mindestens ein View rendert **Flight-Strips als Karten** mit gefelderten
      Spalten (ID/Squawk · Agent · Kind · Zeit · Status) und gruppiert sie in
      Phasen-Buchten (HOLDING/ACTIVE/CLEARED/GO-AROUND).
- [ ] Job-Status-Mapping → Flugphase ist in JS oder CSS eindeutig umgesetzt
      (failed/escalated → GO-AROUND amber, accepted → CLEARED).
- [ ] **Radar-Sweep** als ambiente Animation vorhanden, respektiert
      `prefers-reduced-motion: reduce` (dann statisch, kein Sweep).
- [ ] Kontrast strip-ink/strip-paper ≥ 4.5:1; sichtbarer Tastatur-Fokus;
      responsiv bis 360px ohne horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Sweep); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 1, 2026-06-16. Direktion gewählt, weil
Job-Routing zwischen zwei Maschinen sich exakt auf Tower-Sequencing abbildet,
das echte Flight-Strip-Artefakt die dichten Job-Zeilen natürlich strukturiert,
und B612 (Airbus-Cockpit-Font) das Subjekt typografisch erdet — Duotone hält es
weg vom Ist-Acid-on-black-Default.
