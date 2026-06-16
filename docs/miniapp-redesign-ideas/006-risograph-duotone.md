## Ziel

Gestalte die Miniapp-UI als **Risograph-Zweifarbendruck**. Ein Risodruck lebt
von 1–2 Spot-Farben und sichtbarer Passer-Ungenauigkeit (Misregistration) — und
genau das ist das Produkt: zwei Maschinen (laptop-a = Pink-Platte, laptop-b =
Teal-Platte), und ein sauberer Handoff ist der Moment, in dem beide Platten in
**Passer** liegen. Ein Job ist ein Druckgang; die Farbplatte zeigt, welche
Maschine zuständig ist. Held des Start-Views ist die **lebende Ebenen-Komposition**:
zwei leicht versetzte Farbflächen, die bei einem Handoff in Deckung schnappen.

## Design-Direktion (Token-System)

**Palette** — Papier-Substrat + Riso-Fluoro-Spotfarben + Overprint (das Papier
ist kein Editorial-Cream, sondern bedruckter Träger — definiert durch Fluoro-Inks
+ Halbton, nicht durch Serif):
- `--stock:       #F3EFE6`  — Papier-Substrat (mit Korn-Textur)
- `--ink-pink:    #FF48B0`  — Riso-Fluoro-Pink (Platte laptop-a)
- `--ink-teal:    #1FB3C4`  — Riso-Teal (Platte laptop-b)
- `--ink-key:     #14110F`  — Key-Schwarz (Text, Knockout)
- `--ink-overlap: #5B3A86`  — Überdruck Pink×Teal (Multiply) = beide einig / Handoff komplett
- `--grain`                 — Substrat-Korn (SVG-Noise, mix-blend multiply)

**Typografie**
- Display: **Syne** — eigenwillige Art-Print-Grotesk für Plakat-Headlines.
- Body: **Space Grotesk** — technische Grotesk mit Zine-Charakter.
- Utility/Data: **Space Mono** — Job-IDs, Druckgang-Nummern, Zeiten (Riso-Plakat-Mono).

**Layout** — geschichtete Ink-Komposition; UI-Elemente sind in der Pink- oder
Teal-Platte „gedruckt" und minimal versetzt; Job-Zeilen tragen die Farbe ihrer
Maschine; Füllungen als Halbton-Punktraster. Strukturgeber: **die zwei Ink-Ebenen
+ Überdruckzonen** (Deckung = Einigkeit), keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⊕ press ● in register │
├──────────────────────────────────────────────┤
│  ░░PINK░░ laptop-a        ▒▒TEAL▒▒ laptop-b    │
│   ┌───────┐  offset≈3px  ┌───────┐            │
│   │ task  │╳╳ overlap ╳╳ │ task  │            │ ← misregistration
│   │ 7831  │             │ 2204  │            │
│   └───────┘             └───────┘            │
│  ▦▦▦ halftone fill = progress ▦▦▦              │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — die **Passer-Schnapp-Bewegung**: Pink- und Teal-Ebene eines
Elements liegen um wenige px versetzt; bei `accepted`/Handoff schnappen sie in
exakte Deckung und die Überlappung wird `--ink-overlap` (sichtbarer Beweis eines
sauberen Handoffs). Halbton-Raster als Fortschrittsfüllung. Genau eine Bewegung.
`prefers-reduced-motion: reduce` → Ebenen statisch in Passer, kein Versatz/Schnapp.

## Done-Kriterien

- [ ] `css/tokens.css`: Stock-/Fluoro-/Overlap-Palette + Korn als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Syne, `--font-body` auf Space Grotesk, `--font-mono`
      auf Space Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert UI-Elemente in **zwei versetzten Farbebenen**
      (Pink/Teal) mit `mix-blend-mode: multiply` und Überdruck-Zone.
- [ ] Job-Plattenzuordnung (laptop-a → Pink, laptop-b → Teal) ist eindeutig;
      Fortschritt als **Halbton-Punktraster** dargestellt.
- [ ] Passer-Schnapp-Animation bei Handoff vorhanden, respektiert `prefers-reduced-motion`.
- [ ] Kontrast ink-key/stock ≥ 4.5:1 (Fluoro-Inks NICHT als Fließtext-Farbe);
      sichtbarer Tastatur-Fokus; responsiv bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
  Fluoro-Pink/Teal nur für Flächen/Akzente, nie für kleinen Lauftext.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Passer-Schnapp); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 3, 2026-06-16. Direktion gewählt, weil Risodrucks
Definitionsmerkmal — zwei Spot-Platten + Passer — die Zwei-Maschinen-Architektur
1:1 trägt (Deckung = sauberer Handoff, Overprint = Einigkeit) und ein
Fluoro-Duotone-Print weit weg von allen drei KI-Default-Looks liegt.
