## Ziel

Gestalte die Miniapp-UI als **Sicherheits-Schleuse / Airlock**. Die Risk-Policy
ist fail-closed mit drei Gates (read → build → ops); Ops läuft nie über die
Bridge, Eskalation geht an den Owner. Genau das ist eine Schleuse: ein Job
passiert sequenzielle Schott-Türen, jede mit einer Signalampel, jede muss
freigeben — sonst bleibt die Tür dicht. Owner-Eskalation ist die Aufseher-Kanzel.
Held des Start-Views ist die **Gate-Sequenz** mit ihren Signallampen — keine
Zahl, sondern sichtbare Freigabe-Schritte und das, was (noch) versiegelt ist.

## Design-Direktion (Token-System)

**Palette** — Industrie-Schott: Gunmetal + Warn-Gelb + Signal-Ampel-Triade (kein
Single-Acid-Accent, sondern eine echte Ampel-Semantik auf Stahl):
- `--steel-dark:   #20262B`  — Seitenhintergrund / Recesses
- `--steel:        #3C434A`  — Schott-Bulkheads / Panels (dominant)
- `--caution:      #E8C23A`  — Warn-Streifen (Hazard-Schwellen), Achtung
- `--signal-green: #46D17A`  — Gate frei / clear
- `--signal-amber: #F2A33C`  — Gate prüft / pending (ops/approval)
- `--signal-red:   #E2433B`  — Gate versiegelt / fail-closed
- (Text: `--gauge-white #E6EAEC`, helle Stahlbeschriftung)

**Typografie**
- Display: **Wallpoet** — mechanisch-segmentierte Gate-Readouts, nur in Restraint
  für Schwellen-/Gate-Beschriftung.
- Body: **Public Sans** — neutrale Behörden-/Safety-Signage-Grotesk.
- Utility/Data: **JetBrains Mono** — Gate-Codes, `risk_policy:<regel>`, Job-IDs.

**Layout** — drei sequenzielle Schott-Türen = die drei Gates (read→build→ops);
ein Job wandert Tür für Tür; jede Tür trägt eine Signalampel; fail-closed = Tür
bleibt zu, rote Lampe, Grund `risk_policy:<regel>`. Strukturgeber: **die drei
Gates in echter Reihenfolge + Signallampen + Hazard-Streifen** — hier ist
Nummerierung legitim, weil die Sequenz Information trägt.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ⊟ airlock ● 1 sealed  │
├──────────────────────────────────────────────┤
│ ▤caution▤  GATE 1·READ   GATE 2·BUILD  GATE 3·OPS│
│   task7831 ▮●green────────▮●green──────▮●red   │ ← Job in Sequenz
│            cleared        cleared    risk_policy:│
│                                       ops_offline│
│   ╭ SUPERVISOR ╮ owner-eskalation: 1 wartet     │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — die **Gate-Sequenz-Lampen**: ein Job räumt die Gates der Reihe
nach (read→build→ops), Lampen schalten grün; ein verweigertes Gate bleibt rot und
die Tür versiegelt sichtbar (Bolzen fahren ein). Genau eine Bewegung.
`prefers-reduced-motion: reduce` → Lampen-Endzustand statisch, kein Schalten/Bolzen.

## Done-Kriterien

- [ ] `css/tokens.css`: Stahl-/Caution-/Signal-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Wallpoet (nur Gate-Labels), `--font-body` auf Public
      Sans, `--font-mono` auf JetBrains Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert die **drei Gates als Sequenz mit Signallampen**
      und bildet einen fail-closed-Zustand (rote Lampe + `risk_policy:<regel>`) ab.
- [ ] Status mappt auf Gate-Semantik (accepted = alle grün, abgelehnt = rotes
      Gate mit Regel-Grund); Owner-Eskalation als eigener Hinweis sichtbar.
- [ ] Lampen-/Bolzen-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast gauge-white/steel ≥ 4.5:1; Caution-Gelb nie als kleiner Lauftext;
      sichtbarer Tastatur-Fokus; responsiv bis 360px (Gates stapeln), keine
      horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Gate-Lampen); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 6, 2026-06-16. Erste Facette außerhalb der
Routing-Metaphern: die fail-closed Risk-Policy (read/build/ops, ops nie über die
Bridge, Owner-Eskalation) bildet sich 1:1 auf eine Schleuse mit drei Schotts ab.
Industrie-Stahl + Ampel-Triade statt Single-Acid-Accent.
