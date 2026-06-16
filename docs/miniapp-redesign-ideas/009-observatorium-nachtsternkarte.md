## Ziel

Gestalte die Miniapp-UI als **Observatorium / Nacht-Sternkarte**. Der
Overnight-Scheduler arbeitet die Seed-Queue mitten in der Nacht ab (02:00) und
liefert morgens EINEN Digest — die Nacht ist die echte Betriebszeit. Agenten/
Subsysteme werden zu verfolgten Himmelsobjekten, ein Job ist ein Objekt, das den
**Meridian** kreuzt (queued = Aufgang, running = im Anmarsch, accepted =
Kulmination/Durchgang, escalated = Flare/Nova-Alarm). Held des Start-Views ist
das **lebende Nachtfeld** mit der Meridianlinie und einer Ephemeriden-Tabelle —
keine Zahl, sondern der Lauf der Nacht bis zur Morgendämmerung (Digest).

## Design-Direktion (Token-System)

**Palette** — tiefe Nacht, Sternenlicht, planetares Gold; die Indigo-Violett-Nacht
ist die echte Betriebszeit (überlappt bewusst NICHT mit dem flachen Transit-Navy
— hier Sternfeld + Nebel-Violett):
- `--night-indigo: #141033`  — Nachthimmel, dominante Fläche
- `--night-deep:   #0B0820`  — Vignette / Seitenrand
- `--starlight:    #EDEBF7`  — Sterne, Text
- `--planet-gold:  #E8B85C`  — verfolgte Objekte / aktiver Job (warmer Akzent)
- `--nebula:       #8A6BC4`  — Nebel-Violett, Profil-Akzente (haiku/sonnet/opus)
- `--meridian:     #6FE0C8`  — Meridian-/Durchgangslinie (dünn, kein Flächen-Cyan)

**Typografie**
- Display: **Marcellus** — gravierte, klassische Stern-Atlas-Anmutung, nur in
  Restraint für Titel/Sternbild-Namen.
- Body: **Manrope** — ruhige geometrische Grotesk für Inhalte.
- Utility/Data: **IBM Plex Mono** — Ephemeriden (Aufgang/Durchgang/Untergang), IDs.

**Layout** — Nachtfeld: Subsysteme als **Sternbilder** (verbundene Sterne); Jobs
als Objekte, die auf eine vertikale Meridianlinie zudriften; eine Ephemeriden-
Tabelle listet Rise/Transit/Set = queued/running/done; unten ein Dämmerungs-
Verlauf für den Morgen-Digest. Strukturgeber: **Meridianlinie + Rise/Transit/Set-
Spalten** (echte Astronomie), Sternbild-Linien — keine 01/02-Nummerierung.
```
┌──────────────────────────────────────────────┐
│ ◆ CLAUDE ZENTRALE        ☾ night ● 3 tracked   │
│   · · ✦ codex · · · · ✦ ·  ✦ claude · ·        │
│        ╲constellation╱      │meridian          │
│   EPHEMERIS  obj    rise   transit  set        │
│             ·7831  01:12   02:40   --:--       │ ← Objekt am Meridian
│   ░░░░ dawn gradient → morning digest ░░░░     │
│ [ Start ][ Aktivität ][ Aufgaben ][ Mehr ]     │
└──────────────────────────────────────────────┘
```

**Signature** — der **Meridian-Durchgang**: Objekte (Jobs) driften langsam zum
Meridian; kreuzt eines (accepted), wird es in der Ephemeride geloggt; bei
`escalated` zündet ein Flare. Mit dem Morgen-Digest steigt unten eine
Dämmerung auf. Genau eine ambiente Bewegung. `prefers-reduced-motion: reduce` →
Objekte statisch an ihrer Position, kein Drift, kein Dämmerungs-Fade.

## Done-Kriterien

- [ ] `css/tokens.css`: Nacht-/Sternlicht-/Gold-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, …) konsistent neu verdrahtet.
- [ ] `--font-display` auf Marcellus (nur Titel), `--font-body` auf Manrope,
      `--font-mono` auf IBM Plex Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert ein **Sternfeld mit Meridianlinie** und eine
      **Ephemeriden-Tabelle** (Objekt · rise · transit · set) der Jobs.
- [ ] Status mappt auf Astronomie-Semantik (accepted → Durchgang geloggt,
      escalated → Flare); Profile als Nebel-/Sternbild-Farben.
- [ ] Drift-/Dämmerungs-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast starlight/night-indigo ≥ 4.5:1; sichtbarer Tastatur-Fokus;
      responsiv bis 360px, keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Meridian-Durchgang); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 5, 2026-06-16. Direktion gewählt, weil der
Overnight-Loop buchstäblich nachts läuft und morgens dämmert — die Sternkarte
erzählt Betriebszeit, Ephemeride trägt die Job-Phasen, der Meridian-Durchgang ist
ein ehrliches accepted-Ereignis. Indigo-Nacht + Gold weit weg von Cyan-Obsidian
und allen drei Defaults.
