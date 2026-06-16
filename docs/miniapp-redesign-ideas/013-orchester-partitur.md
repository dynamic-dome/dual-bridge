## Ziel

Gestalte die Miniapp-UI als **Orchester-Partitur / Konzerthaus**. Das Produkt
heißt Orchestr-ator — also nimm den Wortsinn ernst: der Dirigent (Owner) führt,
zwei Notensysteme tragen die beiden Maschinen (laptop-a = oberes System, laptop-b
= unteres), und die Modellprofile sind buchstäblich Werkformen — haiku, sonett,
opus = Tempo-/Satzbezeichnungen. Ein Job ist eine Note/ein Einsatz im Takt; der
Status ist seine Phase im Stück. Held des Start-Views ist die **lebende Partitur**
mit einem wandernden Taktstrich (Playhead) — kein Zähler, sondern ein Stück, das
gespielt wird.

## Design-Direktion (Token-System)

**Palette** — Konzerthaus statt Notenpapier-Cream: Bordeaux-Samt, Messing-Blech,
Elfenbein-Notenlinien, warmes Bühnenlicht (Bordeaux/Messing kommt aus dem
Konzertsaal, nicht aus dem Terracotta-Default):
- `--velvet:      #2A1622`  — Bordeaux-Samt, dominante Fläche
- `--velvet-deep: #1A0E16`  — Logenschatten / Seitenrand
- `--brass:       #C99B43`  — Blechblas-Messing, Primärakzent
- `--ivory-staff: #E9E0CE`  — Notenlinien / Notenpapier-Akzente / Text
- `--spot-warm:   #F0C56A`  — Bühnen-Spotlicht (Playhead-Glow)
- `--string-rose: #B45B6E`  — gedämpftes Rosé (eine Stimmgruppe / Fehler)

**Typografie**
- Display: **Italiana** — elegante Programmheft-Titelei, nur in Restraint für
  Werk-/Satz-Überschriften (Serif bewusst auf dunklem Samt, kein Cream-Default).
- Body: **Albert Sans** — klare Grotesk für Programmnotizen/Inhalte.
- Utility/Data: **JetBrains Mono** — Taktzeiten, Tempo (BPM = Durchsatz), Job-IDs.

**Layout** — Dirigierpartitur: zwei Notensysteme (oben laptop-a, unten laptop-b);
Jobs als Noten/Einsätze entlang der Takte; ein vertikaler Taktstrich (Playhead)
wandert links->rechts und markiert „jetzt"; Profile (haiku/sonett/opus) als
Satz-/Tempo-Überschriften. Strukturgeber: **zwei Notensysteme + Taktstriche +
Playhead + Satzüberschriften** (echte Partitur-Elemente), keine 01/02-Nummerierung.
```
+------------------------------------------------+
| (DIAMOND) CLAUDE ZENTRALE     baton . andante    |
+------------------------------------------------+
| OPUS III - laptop a   |playhead                  |
| ===o====O=======o=====|=========  (oberes system)|
| task7831  task2204    |now                        |
| =====o=========o======|=========  (unteres system)|
| laptop b              |                           |
| [ Start ][ Aktiv ][ Aufgaben ][ Mehr ]           |
+------------------------------------------------+
```

**Signature** — der **Playhead-Taktstrich**: ein vertikaler Lichtstrich wandert
durch die Partitur; Noten leuchten kurz auf, wenn sie „gespielt" werden (Job
startet/endet); accepted = Note klingt voll, failed = Note bricht ab. Genau eine
Bewegung. `prefers-reduced-motion: reduce` -> Playhead statisch auf „jetzt", kein
Wandern/Aufleuchten.

## Done-Kriterien

- [ ] `css/tokens.css`: Samt-/Messing-/Elfenbein-Palette als benannte Tokens;
      Legacy-Mapping (`--bg`, `--accent`, ...) konsistent neu verdrahtet.
- [ ] `--font-display` auf Italiana (nur Überschriften), `--font-body` auf Albert
      Sans, `--font-mono` auf JetBrains Mono; Fonts lokal als woff2 (Preload analog `index.html`).
- [ ] Mindestens ein View rendert **zwei Notensysteme** mit Job-„Noten" und einem
      **Playhead-Taktstrich**; Profile erscheinen als Satz-Überschriften.
- [ ] Status mappt auf Musik-Semantik (accepted = volle Note, failed = Abbruch);
      Durchsatz erscheint als Tempo/BPM.
- [ ] Playhead-/Aufleucht-Animation respektiert `prefers-reduced-motion`.
- [ ] Kontrast ivory-staff/velvet >= 4.5:1; sichtbarer Tastatur-Fokus (Messing);
      responsiv bis 360px (Systeme stapeln), keine horizontale Scrollbar.

## Leitplanken

- Mobile-first, Telegram-Mini-App-Viewport (safe-area, `viewport-fit=cover`).
- a11y-Floor: Fokus sichtbar, reduced-motion respektiert, ARIA-Labels erhalten.
- Token-Disziplin: Farben/Typo nur aus `tokens.css`, kein Inline-Hex.
- Genau **ein** Signature-Bewegungselement (Playhead); keine gestreuten Effekte.

## Herkunft

frontend-design-Loop, Zyklus 7, 2026-06-16. Direktion gewählt, weil „Orchestrator"
wörtlich Orchester bedeutet, die Modellprofile (haiku/sonett/opus) echte Werkformen
sind und zwei Notensysteme die zwei Maschinen tragen. Bordeaux-Samt + Messing statt
Cyan-Obsidian und statt Cream+Serif+Terracotta (Serif nur in Restraint auf Samt).
