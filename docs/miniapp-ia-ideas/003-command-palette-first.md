## Ziel

Mache **„tippen, was du willst"** zum Primärmodell statt der Tab-Navigation. Die
Command-Palette existiert schon (Ctrl/Cmd+K, Fuzzy über Commands/Captures/Jobs/
Todos/Chains), ist aber ein verstecktes Power-User-Feature. These: eine
**persistente Omnibox** im Header, die zugleich sucht, ausführt, anlegt und
springt — wie Spotlight/Raycast für die Zentrale. Das bündelt die heute
verstreuten Create-Entry-Points UND hebt die versteckte Volltextsuche an die
Oberfläche. Tabs bleiben nur als schmales Sicherheitsnetz.

## IA-Konzept

**Primärinteraktion = Omnibox (immer sichtbar im Header):**
Tippen filtert live in vier Ergebnis-Gruppen:
- **Tun** — ausführbare Commands (nur `miniapp_supported`; Rest mit Copy-Fallback)
- **Springe zu** — Captures/Jobs/Todos/Chains/Artifacts (öffnet Detail)
- **Anlegen** — Bridge-Compose (Presets), Reminder, Todo — EIN Einstieg
- **Suchen** — FTS über Verlauf/Captures/Ergebnisse (heutige `/search`)
Leerer Zustand = Vorschläge + zuletzt benutzt (kein leeres Feld).

**Tabs (sekundär, Fallback-Browsing):** Heute · Strom · Bibliothek. Alles
Tieferliegende ist über die Omnibox schneller erreichbar als über Menüs.

**Verknüpfungen:**
- Omnibox ersetzt die 3 Create-Entry-Points (Start-Compose/Aufgaben-Queue/`/remind`).
- Versteckte Suche wandert aus „Mehr" in die immer sichtbare Omnibox.
- Command-Korpus weiter aus `/system/palette`; Ausführung über `/api/chat`.
```
+--------------------------------------------------+
| (icon) [ > tippe befehl, suche, anlegen... ]     | <- persistente Omnibox
|--------------------------------------------------|
|  TUN        /reauth-nlm   /digest jetzt          |
|  SPRINGE ZU  job 7831 (laeuft)  capture "URL..."  |
|  ANLEGEN    + Bridge-Auftrag  + Reminder  + Todo |
|  SUCHEN     "backup" -> 4 Treffer in Verlauf     |
|--------------------------------------------------|
|  [ Heute ] [ Strom ] [ Bibliothek ]              | <- Fallback-Tabs
+--------------------------------------------------+
```

**Signatur-Move:** ein einziges Eingabefeld als Tür zu allem — Suche, Aktion,
Anlegen, Sprung verschmelzen; Menü-Tiefe wird optional.

## Done-Kriterien

- [ ] `index.html`: persistente Omnibox im Header (nicht nur Ctrl/Cmd+K-Modal);
      Tab-Leiste auf Heute/Strom/Bibliothek reduziert.
- [ ] `js/command_palette.js` + `js/palette_fuzzy.js`: von modal-only zu
      persistent erweitert; vier Ergebnis-Gruppen (Tun/Springe/Anlegen/Suchen).
- [ ] Korpus lazy aus `/system/palette`; Command-Ausführung über `/api/chat`
      (nur `miniapp_supported`, sonst Copy-Fallback); Suche nutzt `/search`.
- [ ] „Anlegen" startet Compose/Reminder/Todo aus der Omnibox; Compose nur mit
      erlaubten Presets (Risk-Policy).
- [ ] Leerer Zustand zeigt Vorschläge + zuletzt benutzt; Treffer per Tastatur UND
      Tap wählbar (Touch-Geräte ohne Hardware-Keyboard).
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; jede heutige Funktion bleibt
      erreichbar; Deep-Link-Aliases (`/jobs`,`/search`,…) leiten weiter korrekt.
- [ ] `palette_fuzzy.test.js` grün/erweitert; a11y: ARIA combobox/listbox-Rollen,
      Fokus-Management beim Öffnen/Schließen.

## Leitplanken

- Telegram-Mini-App: Omnibox touch-tauglich, Bildschirmtastatur-freundlich,
  NICHT keyboard-only (jede Aktion auch per Tap).
- **Keine Funktion geht verloren** — Tabs verschlankt, nicht Features entfernt.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: Compose bietet weiterhin nur Presets.
- a11y: combobox/listbox-Semantik, sichtbarer Fokus, reduced-motion.

## Herkunft

IA-Loop, Zyklus 2, 2026-06-16. Adressiert Ist-Schwäche #2 (Suche/Funktionen hinter
„Mehr" versteckt) und #6 (mehrere Create-Entry-Points), indem die bereits
vorhandene Palette-Infrastruktur zum Primärmodell wird. Eingabe-getrieben —
bewusst anders als die Tab-Reorg (001) und der Triage-Stream (002).
