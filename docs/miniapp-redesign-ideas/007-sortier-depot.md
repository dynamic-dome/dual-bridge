## Ziel

Gestalte die Miniapp-UI als **Postamt / Sortier-Depot**. Die Bridge ist ein
Zustelldienst: ein Job ist ein Paket mit Routing-Label, das zwischen zwei Depots
(laptop-a / laptop-b) befördert und an jeder Station **abgestempelt** wird. Der
Status ist der Postweg — eingeliefert (queued), unterwegs (running), zugestellt
(accepted), Annahme verweigert / zurück an Absender (escalated). Held des
Start-Views ist die **Sortier-Wand** mit Paketen in ihren Fächern und sichtbaren
Stempel-/Frankier-Spuren — kein Zähler, sondern ein arbeitendes Depot.

## Design-Direktion (Token-System)

**Palette** — Kraftpapier als dominante Fläche, Luftpost-Chevron + Stempeltinte
(Kraft kommt aus der Paket-Materialität, nicht aus dem Cream-Reflex):
- `--kraft:        #B8895A`  — Kraftpapier-Paket, dominante warme Fläche
- `--kraft-dark:   #6E4A2C`  — Kanten/Schatten, Sekundärtext
- `--airmail-red:  #C8362B`  — Luftpost-Chevron (Rand) / Priorität
- `--airmail-blue: #2B5BA8`  — Luftpost-Chevron (Rand) / Routing
- `--stamp-ink:    #2A2622`  — Gummistempel-/Frankier-Tinte, Haupttext
- `--label-cream:  #EFE7D6`  — Adress-Label-Feld (kleine helle Patches)

**Typografie**
- Display: **Stardos Stencil** — Paket-Schablonen-Typo, nur für Dispatch-/
  Stempel-Header (Restraint).
- Body: **Figtree** — saubere, freundliche Grotesk für Inhalte.
- Utility/Data: **DM Mono** — Sendungsnummern, Routing-Codes, Zeiten.

**Layout** — Sortier-Depot: oben zwei Depot-Bays A/B; darunter ein Fächer-Raster
(Pigeonholes), in dem Pakete (Jobs) mit Routing-Label und Postmark sitzen.
Strukturgeber: **Routing-Labels + Poststempel** (echte Postartefakte), Fächer-
Raster — keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ✉ depot ● 4 in transit│
├──────────────────────────────────────────────┤
│ ▰▱▰ DEPOT A·laptop-a    DEPOT B·laptop-b ▰▱▰   │ ← airmail-chevron
│ ┌─label─┐ ┌─label─┐ ┌─label─┐                 │
│ │RR7831 │ │RR2204 │ │RR6600 │  ◎ZUGESTELLT     │ ← Postmark-Stempel
│ │codex →│ │claude→│ │ ! RTS │                  │
│ └───────┘ └───────┘ └───────┘                 │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — der **Gummistempel-Postmark**: bei Statuswechsel „knallt" ein
runder Stempel aufs Paket (accepted → ZUGESTELLT, escalated → ZURÜCK AN ABSENDER),
leicht rotiert mit Tinten-Unregelmäßigkeit. Genau eine Bewegung.
`prefers-reduced-motion: reduce` → Stempel erscheint ohne Knall-Bewegung.

## Done-Kriterien

- [ ] `css/tokens.css`: Kraft-/Luftpost-/Stempel-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Stardos Stencil (nur Header), `--font-body` auf Figtree,
      `--font-mono` auf DM Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert Jobs als **Pakete mit Routing-Label** in einem
      Fächer-Raster, gruppiert nach Depot A/B.
- [ ] Status mappt auf Postweg-Semantik (accepted → ZUGESTELLT-Stempel,
      escalated → RTS-Stempel) sichtbar als Postmark.
- [ ] Postmark-Stempel-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast stamp-ink/kraft ≥ 4.5:1; sichtbarer Tastatur-Fokus; responsiv bis
      360px (Fächer stapeln), keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Postmark); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 4, 2026-06-16. Direktion gewählt, weil ein
Zustelldienst zwischen zwei Depots das Bridge-Handoff (claimen → befördern →
zustellen, RTS bei Eskalation) wörtlich abbildet und Poststempel ein ehrlicher,
diskreter Statusträger sind — Kraftpapier statt Cream, Luftpost-Rot/Blau statt
Terracotta.
