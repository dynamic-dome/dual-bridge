## Ziel

Gestalte die Miniapp-UI als **Kurzwellen-Relaisstation**. Der Dual-Laptop-Betrieb
ist ein Funk-Relais: zwei Stationen (laptop-a / laptop-b) reichen Sendungen über
eine Verbindung weiter, ein Handoff ist ein „over" mit QSL-Bestätigung. Ein Job
ist eine Sendung mit Rufzeichen; Status wird zum Signalrapport (running = Signal
steht, accepted = QSL bestätigt, failed = „no copy"). Held des Start-Views ist
das **beleuchtete Empfänger-Panel** mit einer ausschlagenden S-Meter-Nadel und
einer Abstimmskala — keine Zahl, sondern ein lebendes Funkgerät.

## Design-Direktion (Token-System)

**Palette** — warmes Bakelit-Chassis, beleuchtete Skala, Messing — die warme
Skala ist eine kleine *leuchtende Fläche*, NICHT der Cream-Default-Hintergrund:
- `--chassis-oxblood: #5A2A24`  — Bakelit-/Oxblood-Chassis, dominante warme Fläche
- `--dial-cream:      #E9DCC0`  — beleuchtete Skalenscheibe (kleines Lichtpanel)
- `--dial-glow:       #FFB347`  — Bernstein-Skalenlicht / Abstimm-Indikator
- `--needle:         #C9352B`  — S-Meter-/VU-Nadel (rot)
- `--brass:          #C7A24A`  — Messing-Knöpfe, Trim, Fokusringe
- `--shadow-walnut:  #1E140F`  — Gehäuseschatten / Text

**Typografie**
- Display: **Oswald** — schmale Skalen-/Frequenznumerals, Geräte-Beschriftung.
- Body: **Work Sans** — humanistische Grotesk, ruhig und warm.
- Utility/Data: **Courier Prime** — Teletype für Rufzeichen, RST-Rapporte, Q-Codes.

**Layout** — Empfänger-Front: oben die Abstimmskala, deren „Frequenzen" die
Agent-Lanes sind (codex/claude); Mitte das S-Meter mit Nadel = aktuelle
Aktivität; darunter das **Logbuch** der Sendungen (Jobs) mit Rufzeichen,
RST-Rapport, QSL-Status. Strukturgeber: **Rufzeichen + RST-Rapporte** (echtes
Funk-Vokabular), Nadel-Gauges — keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⟲ on air ● QSL 3      │
├──────────────────────────────────────────────┤
│  ╭─ TUNE ──────────────────────────────────╮  │
│  │ 3.5    codex    7.0    claude   14.0 MHz │  │ ← Abstimmskala (Lanes)
│  ╰──────────────────────────▲──────────────╯  │
│   S-METER  1·3·5·7··9···▮ +20   ◜needle swing  │ ← Signature
│   LOG  DE7831 codex  RST 599  QSL ✓            │
│        DE2204 claude RST 449  ...  no copy     │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — die **S-Meter-Nadel**: eine analoge Zeigerinstrument-Nadel
schlägt mit der Live-Aktivität aus (Signalstärke = Durchsatz); bei `accepted`
blitzt ein **QSL-Confirm** auf der Skala. Genau eine ambiente Bewegung.
`prefers-reduced-motion: reduce` → Nadel springt ohne Schwung auf den Wert.

## Done-Kriterien

- [ ] `css/tokens.css`: Bakelit-/Skala-/Messing-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Oswald, `--font-body` auf Work Sans, `--font-mono` auf
      Courier Prime; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert ein **S-Meter mit Nadel** (SVG/CSS) und ein
      **Logbuch** der Jobs mit Rufzeichen + RST-Status.
- [ ] Job-Status mappt auf Funk-Semantik (accepted → QSL ✓, failed → „no copy").
- [ ] Nadel-Schwung-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast dial-cream/shadow-walnut bzw. Text/chassis ≥ 4.5:1; sichtbarer
      Tastatur-Fokus (Messingring); responsiv bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Nadel); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 3, 2026-06-16. Direktion gewählt, weil ein Relais
zwischen zwei Funkstationen das Dual-Laptop-Handoff exakt abbildet (over/QSL =
accepted), das analoge Zeigerinstrument eine ehrliche, nicht-digitale
Aktivitätsanzeige liefert und Bakelit-Oxblood bewusst weg vom Ist-Obsidian-Cyan
UND vom Cream-Default führt.
