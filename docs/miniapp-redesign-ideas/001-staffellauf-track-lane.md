## Ziel

Gestalte die Miniapp-UI als **Leichtathletik-Staffelbahn von oben**. Die Bridge
ist buchstäblich eine Staffel: im `relay-loop` reichen codex@laptop-b und
claude@laptop-a den Stab weiter, die Rolle wechselt bei `accepted`. Der Code hat
die Metapher schon halb angelegt (`--lane-haiku/sonnet/opus`). Der Start-View
öffnet als Blick von oben auf eine Tartanbahn: zwei aktive Bahnen (A = codex,
B = claude), ein Stab, der gerade in einer Hand liegt, und eine **Wechselzone**,
die aufleuchtet, wenn ein Handoff (accepted) passiert. Held der Seite ist die
laufende „aktuelle Etappe", nicht eine große Zahl.

## Design-Direktion (Token-System)

**Palette** — die Bahnfläche ist die *dominante* Fläche (invertiert den
Cream-+-Terracotta-Default; das Rostrot kommt aus der echten Tartan-Materialität,
nicht aus dem Default-Reflex), gepaart mit kühlem Rasen-Infield statt Cream:
- `--track-clay:  #B5432B`  — gummierte Bahnfläche, dominante Hintergrundfläche
- `--infield:     #2F5D3A`  — Rasen-Infield, sekundäre Panels/Cards
- `--lane-line:   #F2EAD9`  — Kalk-Bahnlinien (Trenner, Hairlines mit Zweck)
- `--baton-gold:  #F4B33C`  — der Stab / die aktive Etappe (einziger Spot-Akzent)
- `--cinder:      #1A1410`  — Aschenbahn-Tiefschwarz (Text-Kanten, Schatten)
- `--chalk:       #FBF7EE`  — Text auf clay

**Typografie**
- Display: **Anton** oder **Saira Condensed** — schmale Stadion-/Startnummern-Typo
  für Bahnnummern und große Etappen-Labels (Trikotnummern-Anmutung).
- Body: **Archivo** — neutrale Grotesk mit sportlicher Strenge.
- Utility/Data: **JetBrains Mono** — Zwischenzeiten, Job-IDs, Splits (Mono = Stoppuhr).

**Layout** — Bahnen sind horizontale Zeilen; jeder laufende Job ist eine Bahn mit
einem Läufer-Punkt, der links→rechts läuft; die Wechselzone sitzt in der Mitte.
Strukturgeber: **Bahnnummern** (1, 2) als echte Identität, nicht als Deko-Sequenz.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE          status ● live      │
├──────────────────────────────────────────────┤
│ AKTUELLE ETAPPE  ▸ task-7831  codex→claude    │  ← Hero: live leg
│                                                │
│ 1 │codex ●────────────▮ [STAB]      04:12     │  ← Bahn A
│   │           ╎ WECHSELZONE ╎                  │  ← exchange zone
│ 2 │claude ─────────○                  --:--   │  ← Bahn B (wartet)
│                                                │
│ [ Inbox ] [ Aktivität ] [ Aufgaben ] [ Mehr ] │
└──────────────────────────────────────────────┘
```

**Signature** — der **Stab-Pass an der Wechselzone**: bei `accepted` gleitet ein
goldener Stab von einer Bahn in die nächste, mit einem kurzen Kalk-Staub-Puff.
Plus ein **Staffelstart-Reveal** beim Laden (Bahnen zeichnen sich versetzt ein
wie die gestaffelten Startlinien einer Bahn). Genau eine orchestrierte Bewegung;
sonst Ruhe.

## Done-Kriterien

- [ ] `css/tokens.css`: neue Palette als benannte Tokens gesetzt; das
      Legacy-Mapping (`--bg`, `--accent`, …) zeigt auf die neuen Werte, sodass
      bestehende Styles nicht brechen.
- [ ] `--font-display` auf eine kondensierte Stadion-Typo, `--font-body` auf
      Archivo umgestellt; `--font-mono` bleibt JetBrains Mono. Fonts lokal
      eingebunden (woff2-Preload analog `index.html`), kein externer CDN-Block.
- [ ] Der Start-View rendert mindestens eine **Bahn-Zeile** mit Bahnnummer und
      einem Fortschritts-/Läufer-Indikator; aktive Etappe ist als Hero oben sichtbar.
- [ ] **Stab-Pass-Animation** an der Wechselzone existiert und respektiert
      `prefers-reduced-motion: reduce` (dann sofortiger Zustandswechsel ohne Slide).
- [ ] Sichtbarer Tastatur-Fokus auf allen Tabs/Buttons; Kontrast Text/clay ≥ 4.5:1.
- [ ] Responsiv bis 360px Breite (Telegram-Mini-App), keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (`viewport-fit=cover`, safe-area).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo ausschließlich aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement; keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 1, 2026-06-16. Direktion gewählt, weil die
relay-loop-Staffel-Metapher schon im Code steckt (`--lane-*`, „Stab", Rollen-
wechsel bei accepted) und die Tartan-Materialität ein Default-Hex (Terracotta)
legitim als *Fläche statt Akzent* einsetzt — bewusst weg vom Ist-Obsidian-Cyan.
