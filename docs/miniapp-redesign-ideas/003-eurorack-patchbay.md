## Ziel

Gestalte die Miniapp-UI als **modulares Eurorack-Patchbay**. Der Orchestrator
IST ein Patchfeld: jedes Subsystem ist ein Rack-Modul (`tokens.css` führt sie
schon als Farben — bridge, codex, worker, portier, mcp, notebooklm, security),
und ein Job ist ein **Patchkabel**, das Signal von der OUT-Buchse eines Moduls
zur IN-Buchse eines anderen routet. Die Bridge ist das Kabel, das zwei Racks
überspannt (laptop-a / laptop-b). Held des Start-Views ist das **Live-Patchfeld**:
welche Module gerade verkabelt sind, nicht eine Zahl. Buchsen-LEDs zeigen Signal.

## Design-Direktion (Token-System)

**Palette** — gebürstetes Aluminium + Graphit-Panels im dunklen Rack, Kabel in
Bonbon-Signalfarben (kommt aus der Subsystem-Materialität, nicht aus dem
Acid-on-black-Default — hier ein ganzes Kabel-Spektrum, kein Single-Accent):
- `--rack-void:      #17181B`  — Rack-Innenraum / Seiten-Hintergrund
- `--panel-alu:      #BCC0C6`  — gebürstete Alu-Modulfront (helle Module/Cards)
- `--panel-graphite: #34383E`  — Graphit-Modulfront (sekundäre Module)
- `--silk-dark:      #1A1B1E`  — Siebdruck-Labels auf Alu (dunkler Text)
- `--jack-led:       #5BE08C`  — Buchsen-LED grün (verkabelt/aktiv)
- `--cable-hot:      #E0483C`  — Kabel-Akzent (zusätzlich Subsystem-Farben als Kabel)

**Typografie**
- Display: **Chakra Petch** — quadratisch-technische Synth-Panel-Typo für
  Modulnamen (Eurorack-Siebdruck-Anmutung).
- Body: **Hanken Grotesk** — ruhige Grotesk für Beschreibungen/Status.
- Utility/Data: **JetBrains Mono** — Buchsen-Werte, CV, Job-IDs.

**Layout** — vertikale Rack-Reihen aus Modulen; jedes Subsystem ein Modul mit
Buchsenreihe; ein Job ist ein leuchtender Kabel-Bogen von der OUT-Buchse der
Quelle zur IN-Buchse des Ziels. Strukturgeber: **Modulgrenzen + Buchsenreihen**,
keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ▮ patch ● 2 cables    │
├──────────────────────────────────────────────┤
│ ┌RACK A·laptop-a─────┐   ┌RACK B·laptop-b────┐ │
│ │ CODEX     ○ ○ ●OUT │╲  │ CLAUDE  IN●  ○ ○  │ │
│ │ ▮▮▮▮  led●live     │ ╲_│ ▮▮▮▮               │ │  ← bridge-Kabel
│ │ WORKER    ○ ○ ○    │   │ MCP     ○ ○ ○     │ │
│ └────────────────────┘   └───────────────────┘ │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — das **Patchkabel mit Catenary-Sag**: bei aktivem Routing
verbindet ein Kabel zwei Buchsen mit leichtem physikalischem Durchhang; der
Bridge-Job spannt das Kabel zwischen den beiden Racks. Kabel wackelt beim
Erscheinen kurz aus. `prefers-reduced-motion: reduce` → statisches Kabel ohne Wackeln.

## Done-Kriterien

- [ ] `css/tokens.css`: Rack-/Alu-/Graphit-Palette als benannte Tokens; die
      vorhandenen `--subsystem-*`-Farben werden als Kabelfarben wiederverwendet;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Chakra Petch, `--font-body` auf Hanken Grotesk;
      `--font-mono` bleibt JetBrains Mono. Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert **Subsysteme als Module mit Buchsenreihe** und
      mindestens einen **Kabel-Bogen** (SVG-Pfad) zwischen zwei Buchsen für einen
      aktiven Job.
- [ ] Buchsen-LED-Zustand bildet Job-Status ab (live = grün, failed = `--cable-hot`).
- [ ] Catenary-Kabel-Animation vorhanden, respektiert `prefers-reduced-motion`.
- [ ] Kontrast silk-dark/panel-alu ≥ 4.5:1; sichtbarer Tastatur-Fokus; responsiv
      bis 360px (Racks stapeln vertikal), keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Patchkabel); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 2, 2026-06-16. Direktion gewählt, weil die
Subsystem-Farben in `tokens.css` schon ein Patchfeld-Vokabular anlegen und
„Job = Signal-Routing zwischen Modulen, Bridge = Kabel zwischen zwei Racks" das
Orchestrator-Modell physisch greifbar macht — Kabel-Spektrum statt Single-Accent.
