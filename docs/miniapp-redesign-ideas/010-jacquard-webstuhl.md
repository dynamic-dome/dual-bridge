## Ziel

Gestalte die Miniapp-UI als **Jacquard-Webstuhl mit Lochkarten**. Die
Jacquard-Lochkarte ist der direkte Vorfahr der programmierbaren Maschine — die
perfekte Metapher für einen Orchestrator, der Job-Specs einliest und abarbeitet.
Ein Job IST eine Lochkarte (sein Spec = das Lochmuster); die Maschine liest die
Karte und **webt** daraus eine Stoffreihe. Zwei Compositeure (laptop-a / laptop-b)
arbeiten am selben Gewebe; fertige Jobs wachsen als Jacquard-Muster zu einem Tuch.
Held des Start-Views ist das **wachsende gewebte Band** plus die Karte, die gerade
eingelesen wird — kein Zähler, sondern sichtbar geleistete Arbeit.

## Design-Direktion (Token-System)

**Palette** — Leinen-Gewebe, Walnuss-Rahmen, die zwei klassischen Faden-Färbungen
Indigo + Krapp als die zwei Maschinen-/Lane-Farben (Färber-Materialität, nicht
Terracotta-Reflex; das Leinen ist durch Webtextur definiert, kein Editorial-Cream):
- `--linen:        #D9CDB0`  — Leinen-Gewebe/Tuch, Grundfläche (mit Web-Textur)
- `--walnut:       #43301E`  — Webstuhl-Rahmenholz, Struktur + Text
- `--indigo-dye:   #2E4A6B`  — indigogefärbter Faden (Lane laptop-a)
- `--madder:       #A6402F`  — krapprot gefärbter Faden (Lane laptop-b)
- `--brass-heddle: #B89046`  — Messing-Litzen/Beschläge, Akzent/Fokus
- `--card-cream:   #ECE3CE`  — Lochkartenpapier

**Typografie**
- Display: **Bricolage Grotesque** — charaktervolle zeitgenössische Grotesk für
  Atelier-/Sektions-Header (kein High-Contrast-Serif → meidet Default).
- Body: **Karla** — warme Grotesk für Inhalte.
- Utility/Data: **Major Mono Display** — Lochkarten-Binär-Readouts (Job-Spec als
  Lochmuster), Job-IDs — evoziert Früh-Computer-Ausdrucke.

**Layout** — Webstuhl: oben die Kettfäden (vertikal, Indigo/Krapp) mit Litzen;
eine **Lochkarte** schiebt sich ein und kodiert den aktuellen Job (Löcher = Spec);
darunter ein **wachsendes Webband**, in dem jeder fertige Job eine Musterreihe
ergänzt. Strukturgeber: **Lochkarten-Lochraster (binär) + gewebte Reihen** (echtes
Programm → Ausgabe), keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⊞ loom ● weaving      │
│  ‖indigo‖ warp ‖madder‖   heddles ▤▤▤          │
│  ┌ CARD ───────────────┐                       │
│  │ ·o··o·o···o· task7831│ ← Lochmuster = Spec   │
│  └──────────────────────┘                      │
│  ▦▩▦▩ woven band (done jobs add rows) ▩▦▩▦     │ ← Signature
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — das **wachsende Webband**: jeder fertige Job webt eine neue
Jacquard-Musterreihe ans Tuch (Indigo/Krapp je nach Maschine); beim Start eines
Jobs schiebt sich seine Lochkarte ein. Genau eine Bewegung.
`prefers-reduced-motion: reduce` → Karte/Reihe erscheinen ohne Schiebe-/Web-Animation.

## Done-Kriterien

- [ ] `css/tokens.css`: Leinen-/Walnuss-/Indigo-/Krapp-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Bricolage Grotesque, `--font-body` auf Karla,
      `--font-mono` auf Major Mono Display; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert eine **Lochkarte** (Lochraster als Job-Spec) und
      ein **gewebtes Band**, das pro fertigem Job eine Reihe ergänzt.
- [ ] Maschinen-Zuordnung über Fadenfarbe (laptop-a → Indigo, laptop-b → Krapp);
      Job-Phase sichtbar (Karte eingelesen = running, Reihe gewebt = accepted).
- [ ] Web-/Karten-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast walnut/linen ≥ 4.5:1; sichtbarer Tastatur-Fokus (Messing-Litze);
      responsiv bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Webband); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 5, 2026-06-16. Direktion gewählt, weil die
Jacquard-Lochkarte der historische Ursprung der programmierbaren Maschine ist
(Job-Spec = Lochmuster) und das wachsende Tuch geleistete Arbeit ehrlich
materialisiert. Indigo+Krapp sind echte Färber-Fäden als die zwei Lanes — bewusst
nicht der Terracotta-Default.
