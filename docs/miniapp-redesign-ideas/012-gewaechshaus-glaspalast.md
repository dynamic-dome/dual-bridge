## Ziel

Gestalte die Miniapp-UI als **Gewächshaus / Glaspalast**. Das Projekt nennt seine
Overnight-Aufträge buchstäblich **Seeds** (`docs/overnight/*.md` → goal-loop) — ein
Gewächshaus ist also keine Metapher von außen, sondern die eigene Vokabel: ein
Seed wird über Nacht eingepflanzt, keimt, und der Morgen-Digest ist die Ernte. Ein
Job ist eine Pflanze, deren Wachstumsstufe den Status trägt — Saat (queued),
Keimling (running), Blüte (accepted), Welke (failed). Held des Start-Views ist die
**Glashaus-Bank** mit wachsenden Pflanzen — kein Zähler, sondern reifende Arbeit.

## Design-Direktion (Token-System)

**Palette** — Viktorianischer Glaspalast: helles Glaslicht (grünstichig, KEIN
Cream), dunkelgrüne Glasleisten-Eisen, Laubgrüns, eine Blüten-Akzentfarbe:
- `--glasshouse:  #EAF1EC`  — Glaslicht-Innenraum, helle Grundfläche (grünstichig)
- `--iron-bar:    #2F4A3A`  — Glasleisten-Eisen (Struktur + Text)
- `--fern:        #4E8C5A`  — Laubgrün, primär
- `--moss:        #6FA663`  — helleres Wachstum / sekundär
- `--soil-umber:  #5A4530`  — Erde / Saatgut
- `--bloom:       #E0578B`  — Blüten-Akzent (Koralle-Magenta), accepted/Blüte

**Typografie**
- Display: **Schibsted Grotesk** — klare, charaktervolle Header (kein Serif → meidet
  den Botanik-Plakat-Cream-Default).
- Body: **Mulish** — leichte humanistische Grotesk für Inhalte.
- Utility/Data: **Spline Sans Mono** — Latin-Specimen-Tags der Jobs, IDs, Zeiten.

**Layout** — Glashaus-Bank mit Pflanztöpfen; jeder Job eine Pflanze in ihrer
Wachstumsstufe (Saat→Keimling→Blüte→Welke); ein Glasleisten-Gitter rahmt die
Scheiben. Strukturgeber: **Wachstumsstufen (echte Sequenz) + Glasleisten-Gitter**,
Latin-Specimen-Tags — keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ❀ glasshouse ● 5 wachsen│
├──────────────────────────────────────────────┤
│  ╪═══════════ glazing-bar grid ═══════════╪    │
│  🌱        🌿          ❀           ✕          │
│  Saat     Keimling    Blüte (accepted) Welke   │ ← Wachstumsstufe = Status
│ ‹seed:07› ‹task7831›  ‹task2204›   ‹task6600›  │
│  overnight → morning harvest (digest)          │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — die **wachsende Pflanze**: jede Pflanze rückt eine Wachstumsstufe
vor, wenn ihr Job fortschreitet; über Nacht laufen die Seeds als Zeitraffer zur
Morgenernte (Digest). Genau eine Bewegung. `prefers-reduced-motion: reduce` →
Wachstumsstufe statisch dargestellt, kein Zeitraffer.

## Done-Kriterien

- [ ] `css/tokens.css`: Glaslicht-/Eisen-/Laub-/Blüten-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Schibsted Grotesk, `--font-body` auf Mulish,
      `--font-mono` auf Spline Sans Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert Jobs als **Pflanzen in Wachstumsstufen**
      (Saat/Keimling/Blüte/Welke) hinter einem Glasleisten-Gitter.
- [ ] Status mappt auf Wachstum (accepted → Blüte `--bloom`, failed → Welke);
      Overnight-Seeds erkennbar als Saatgut.
- [ ] Wachstums-/Zeitraffer-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast iron-bar/glasshouse ≥ 4.5:1; sichtbarer Tastatur-Fokus; responsiv
      bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Wachstum); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 6, 2026-06-16. Direktion gewählt, weil „Seed" die
echte Projekt-Vokabel ist (Overnight-Seeds → goal-loop → Morgen-Digest) — ein
Gewächshaus erzählt Einpflanzen/Keimen/Ernten wörtlich. Grün-dominante Palette
füllt eine Lücke im Katalog, helles Glaslicht statt Cream.
