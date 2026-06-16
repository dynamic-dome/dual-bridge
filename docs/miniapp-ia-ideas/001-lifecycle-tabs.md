## Ziel

Ordne die Mini-App nach dem **Arbeits-Lebenszyklus** statt nach Entitätstypen.
Heute hat jede Datenart einen eigenen Tab (Inbox, Aktivität, Kalender, Aufgaben,
Ergebnisse), wodurch dieselbe Nutzer-Absicht über mehrere Tabs zerfällt und
wertvolle Funktionen (Suche/Verlauf/Workflows/Nutzung) hinter „Mehr" verschwinden.
Neue These: **vier Tabs entlang der Verben** — was kommt rein, was wird bearbeitet,
was kam raus, was lerne ich daraus. Plus eine **persistente globale Suche im
Header**, damit sie nicht mehr 3 Klicks tief liegt.

## IA-Konzept

**Tab-Struktur (4 statt 7):**
1. **Heute** — abgespecktes Start: NUR was mich jetzt braucht (offene Freigaben,
   Attention-Jobs, fällige Reminders). Catch-all-Lanes + Compose-Form ziehen weg.
2. **Eingang** — alles Reinkommende UND Anlegen an einem Ort: Captures (heutige
   Inbox) + „Neu" (Bridge-Compose mit Presets, Reminder, Todo) als ein Create-Flow.
3. **Arbeit** — heutige Aktivität: Jobs + Approvals + Chains, aber klar in
   Unter-Lanes „Wartet auf mich / Läuft / Erledigt"; Chains als gruppiert-
   aufklappbare Einheiten statt untergemischt.
4. **Wissen** — Konsum + Analyse zusammen: Ergebnisse (Artifacts) + die bisher
   versteckten Verlauf, Nutzung, Workflows als deep-linkbare Unter-Routen.

**Kalender/Reminders:** als „Heute"-Sektion + Header-Glocke; kein eigener Tab mehr.

**Verknüpfungen:**
- Globale **Suche** wandert in den Header (immer sichtbar), Command-Palette bleibt.
- Mehr-Bottom-Sheet entfällt; seine Sub-Views (Verlauf/Suche/Nutzung/Workflows)
  werden echte Routen unter „Wissen" (Browser-Back + Deep-Link funktionieren).
- Bestehende Router-Aliases bleiben gültig (/jobs|/approvals→Arbeit,
  /history|/analytics|/search|/explorer→Wissen, /home→Heute).
```
+--------------------------------------------------+
| (icon) CLAUDE ZENTRALE      [ Suche... ]  (bell) | <- Header-Suche + Reminder-Glocke
|--------------------------------------------------|
|  HEUTE: 2 Freigaben warten . 1 Job laeuft        |
|         . Reminder in 2h                          |
|--------------------------------------------------|
|  [ Heute ] [ Eingang ] [ Arbeit ] [ Wissen ]     | <- 4 Tabs
+--------------------------------------------------+
  Eingang -> "Neu": Compose | Reminder | Todo (ein Flow)
  Arbeit  -> Wartet auf mich / Laeuft / Erledigt (Chains gruppiert)
  Wissen  -> Ergebnisse | Verlauf | Nutzung | Workflows (Routen)
```

**Signatur-Move:** „Neu" als EIN Create-Einstieg statt drei verstreuter
Entry-Points (Start-Compose / Aufgaben-Queue / /remind).

## Done-Kriterien

- [ ] `index.html`: Tab-Leiste auf 4 Tabs (Heute/Eingang/Arbeit/Wissen) reduziert;
      Header bekommt ein persistentes Such-Eingabefeld + Reminder-Indikator.
- [ ] `js/app.js`: Router kennt die 4 neuen Views; ALLE bestehenden Aliases
      (/home,/jobs,/approvals,/history,/analytics,/search,/explorer) leiten korrekt
      auf die neuen Ziele (keine toten Deep-Links).
- [ ] „Arbeit" zeigt Jobs+Approvals+Chains in drei Unter-Lanes (Wartet/Läuft/
      Erledigt); Chains erscheinen als gruppierte, aufklappbare Einheit.
- [ ] „Wissen" macht Verlauf/Nutzung/Workflows zu deep-linkbaren Unter-Routen
      (kein Bottom-Sheet); Zurück-Navigation per Browser-Back möglich.
- [ ] „Eingang" bündelt Capture-Liste + einen „Neu"-Flow (Compose/Reminder/Todo);
      Bridge-Compose nutzt weiterhin NUR die erlaubten Presets (Risk-Policy).
- [ ] **Funktions-Parität:** jede heute erreichbare Funktion ist nachweisbar weiter
      erreichbar (Mapping-Tabelle alt→neu im PR); keine Capability verschwindet.
- [ ] Bestehende JS-Tests (`*.test.js`) grün bzw. angepasst; a11y-Floor erhalten.

## Leitplanken

- Telegram-Mini-App: Tab-Leiste bleibt daumenfreundlich (≤4-5 Top-Level), safe-area.
- **Keine Funktion geht verloren** — nur Umordnung/Bündelung, kein Feature-Cut.
- Deep-Link-Aliases bleiben funktionsfähig (Abwärtskompatibilität).
- Risk-Policy: Compose bietet weiterhin nur Presets, kein freies kind/adapter.
- a11y: Fokus sichtbar, ARIA-Labels, reduced-motion respektiert.

## Herkunft

IA-Loop, Zyklus 1, 2026-06-16. Adressiert Ist-Schwäche #1 (3 Konzepte vermischt),
#2 (versteckte Funktionen hinter Mehr) und #6 (mehrere Create-Entry-Points) durch
eine lebenszyklus-orientierte 4-Tab-Struktur mit Header-Suche.
