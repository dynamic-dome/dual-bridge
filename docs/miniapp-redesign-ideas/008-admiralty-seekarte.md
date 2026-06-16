## Ziel

Gestalte die Miniapp-UI als **Admiralitäts-Seekarte**. Die Bridge überbrückt
Wasser zwischen zwei Küsten (laptop-a / laptop-b); ein Job ist ein **gesteuerter
Kurs** über die See, der Status seine Lage — abgesteckt (queued), in Fahrt
(running), vor Anker / zugestellt (accepted), auf Grund (escalated). Tiefenangaben
(Soundings) zeigen den Aufwand eines Jobs. Held des Start-Views ist die **lebende
Karte** mit der gezeichneten Kurslinie zwischen den Küsten und einer Kompassrose —
keine Zahl, sondern Navigation.

## Design-Direktion (Token-System)

**Palette** — echte Admiralitäts-Kartenkonvention: Büttenpapier-Land, getöntes
Wasser, **Magenta** als Warnsymbol-Akzent (kommt aus der Kartenmaterialität, NICHT
aus dem Terracotta-Default; das Buff ist Seekartenpapier, kein Editorial-Cream):
- `--chart-buff:   #E4D9B8`  — Landmassen / Kartenpapier-Basis
- `--water-shoal:  #BBD9DE`  — Flachwasser-Tönung
- `--water-deep:   #5C8FA6`  — Tiefwasser
- `--sounding-ink: #1C2B33`  — Soundings, Tiefen-Numerals, Text
- `--magenta-mark: #C0398B`  — Admiralitäts-Magenta: Warn-/Kurs-Symbole, Akzent
- `--contour:      #F4EFE0`  — weiße Tiefenlinien (Höhenlinien des Meeresbodens)

**Typografie**
- Display: **Cormorant** — gravierte Karten-Titel + Kompassrose, nur in Restraint
  (Karten-Titelei ist historisch Serif — bewusste Subjekt-Wahl, kein Default-Reflex).
- Body: **Inter** — neutrale Grotesk für Inhalte (hält es weg vom Editorial-Look).
- Utility/Data: **JetBrains Mono** — Soundings, Kurs-Bearings, Job-IDs.

**Layout** — schematische Seekarte: Wasser mit Tiefenlinien zwischen zwei
Küstenstreifen A/B; Kurslinien (gestrichelt, magenta) verbinden Wegpunkte =
Job-Phasen; eine Kompassrose verankert die Orientierung. Strukturgeber:
**Tiefenlinien + Soundings + Kompass-Bearings** (echte Kartenelemente), keine
01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ✛ chart ● 2 underway  │
├──────────────────────────────────────────────┤
│ ▓LAND·laptop-a▓   ·12·   ·24·    ▓LAND·b▓      │
│        ╲ ⌖ 047°╌╌╌╌╌╌●╌╌╌╌╌╌⚓ accepted          │ ← Kurslinie (magenta)
│   ((( )))  ·18·     running   ·31·  ·soundings· │
│   compass         ~~~ contour ~~~              │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — die **gezeichnete Kurslinie**: eine gestrichelte Magenta-Kurslinie
zeichnet sich zwischen den Wegpunkten, während ein Job fortschreitet; bei
`accepted` fällt das Anker-Symbol, bei `escalated` blinkt ein Untiefen-Warnsymbol.
Genau eine Bewegung. `prefers-reduced-motion: reduce` → Kurslinie statisch
vollständig, kein Zeichnen.

## Done-Kriterien

- [ ] `css/tokens.css`: Karten-Palette (Buff/Wasser/Magenta) als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Cormorant (nur Titel/Kompass), `--font-body` auf Inter,
      `--font-mono` auf JetBrains Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert den **Job-Lebenszyklus als Kurslinie mit
      Wegpunkten** (SVG) zwischen zwei Küstenstreifen A/B, mit Tiefenlinien-Hintergrund.
- [ ] Status mappt auf Navigations-Semantik (accepted → Anker, escalated →
      Untiefen-Warnsymbol magenta); Soundings stellen Job-Aufwand dar.
- [ ] Kurslinien-Zeichen-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast sounding-ink/chart-buff ≥ 4.5:1; sichtbarer Tastatur-Fokus;
      responsiv bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Kurslinie); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 4, 2026-06-16. Direktion gewählt, weil „einen Kurs
über Wasser zwischen zwei Küsten stecken" das Routing zwischen laptop-a/b
kartografisch erzählt, Soundings den Job-Aufwand tragen und die echte
Admiralitäts-Magenta-Konvention einen Akzent liefert, der bewusst NICHT der
Cream+Serif+Terracotta-Default ist (Serif nur in Restraint für Karten-Titelei).
