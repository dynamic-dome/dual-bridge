# Miniapp-IA/UX-Umbau — Ideen-Queue

Nachfolger der rein ästhetischen `../miniapp-redesign-ideas/`. Hier geht es NICHT
um Farben/Typo, sondern um die **Informationsarchitektur** der ganzen Mini-App:
Tab-Anordnung, Inhalt/Funktionen pro Seite und die **Verknüpfung der Funktionen
untereinander**. Alle ~5 Min entstehen 2 neue, distinctive IA/UX-Direktionen als
ausführbarer Bridge-Task (goal-loop/relay-Seed) gegen das DCO-Repo.

## Ist-Architektur (Ground Truth — Stand 2026-06-16)

**Code:** `dynamic_central_orchestrator/miniapp/` — Tabs in `index.html`, Router/
Aliases in `js/app.js`, Views je `js/<view>.js`, API in `js/api.js`.

**7 Tabs:** Start · Inbox · Aktivität · Kalender · Aufgaben · Ergebnisse · Mehr
- **Start** = Catch-all-Dashboard: System-Status, Bridge-Compose-Form (Presets
  Bauen/Test/Review/Recherche/Smoke), 4 Lanes (aktive Jobs, Freigaben, Reminders, Feed).
- **Inbox** = Captures (Text/URL/Voice/Doc/Foto) mit Filter + Suche.
- **Aktivität** = Jobs + Approvals + Chains fusioniert; Filter-Pills; `approval-badge`.
- **Kalender** = Reminders als Countdown-Timeline + Recurrence + Create-Form.
- **Aufgaben** = Todos mit Tag-Filter + Stale-Badges; Queue-Button (→ Job).
- **Ergebnisse** = Artifacts (Briefings/Audio/Recherche/Chains), read-only.
- **Mehr** = Hub; öffnet im Bottom-Sheet: **Verlauf**, **Suche**, **Nutzung**, **Workflows/Explorer**, Reauth-NLM.
- **Global:** Command-Palette (Ctrl/Cmd+K, Fuzzy über Commands/Captures/Jobs/Todos/
  Chains), geteiltes `#detail-overlay` für alle Detail-Ansichten + QuickForm.
- **Router-Aliases (app.js):** /home→start, /jobs|/approvals→activity,
  /explorer|/analytics|/history|/search→more (openSubView=…).

**Bekannte IA-Schwächen (Grundlage für Vorschläge):**
1. **3 Top-Level-Konzepte vermischt:** Arbeit (Jobs/Approvals/Chains) ↔ Konsum
   (Ergebnisse/Reminders) ↔ Analyse (Suche/Nutzung/Verlauf/Workflows).
2. **Wertvolle Funktionen versteckt** hinter Mehr → Bottom-Sheet (Suche, Verlauf,
   Workflows, Nutzung) — 2-3 Klicks tief, nicht deep-linkbar, kein Browser-Back.
3. **Approvals an 3 Stellen** (Start-Lane + Aktivität-Filter + Mehr-Karte) — keine
   eindeutige Heimat, kein Approval-Verlauf (entschiedene verschwinden).
4. **Start überladen** (4 Lanes + Compose-Form) → viel Scroll, Priorität unklar.
5. **Chains** konzeptionell anders als Einzeljobs (eigenes Status-Modell), aber in
   Aktivität untergemischt.
6. **Mehrere Entry-Points fürs selbe** (Reminder anlegen: Kalender-Form / /remind /
   Start-Hint; Task anlegen: Start-Compose / Aufgaben-Queue / Palette).

## Format jeder Idee
Bridge-Task-Seed PLUS IA-Konzept:
```
## Ziel              — die IA-These (Organisationsprinzip) in einem Absatz
## IA-Konzept        — Tab-Struktur, Inhalt/Funktionen pro Seite, Verknüpfungen
                       (+ ASCII-Nav/Flow-Diagramm, reine ASCII)
## Done-Kriterien    — konkret, referenziert echte Dateien (index.html Tabs,
                       app.js Router/Aliases, Views); KEINE Funktion geht verloren
## Leitplanken       — Telegram-Mini-App, a11y, Funktions-Parität, Deep-Links erhalten
## Herkunft          — Zyklus, Datum, welche Ist-Schwäche adressiert
```

> **Status (2026-06-16):** Loop abgeschlossen nach 10 Direktionen → Bewertung &
> Empfehlung in [`000-SYNTHESE.md`](000-SYNTHESE.md). Empfohlenes Zielbild:
> 001 Lifecycle-Tabs als Frame + Bausteine 004 (Cross-Links) · 003 (Header-Omnibox) · 005 (Chains-Pipeline).

## Bereits vergebene Direktionen (keine Wiederholung)
| # | Direktion | Organisationsprinzip | Datum |
|---|-----------|----------------------|-------|
| 000 | **SYNTHESE & Empfehlung** | Bewertung der 10 + Kombinierbarkeit + Top-Auswahl | 2026-06-16 |
| 001 | Lifecycle-Tabs (4 statt 7) | nach Arbeits-Lebenszyklus/Verben statt Entitätstypen | 2026-06-16 |
| 002 | Action-Inbox (Triage-Stream) | eine priorisierte „braucht mich"-Spalte als Rückgrat | 2026-06-16 |
| 003 | Command-Palette-first | persistente Omnibox (suchen/tun/anlegen/springen) als Primärmodell | 2026-06-16 |
| 004 | Master-Detail + Cross-Links | Beziehungen (Job↔Artifact↔Quelle↔Chain) als deep-linkbare Routen | 2026-06-16 |
| 005 | Chains als Pipeline-Bereich | Chains aus Aktivität lösen, eigener Bereich mit Schritt-Pipeline + Fehler-Gate | 2026-06-16 |
| 006 | Rollen-Modi / Progressive Disclosure | Beobachter (read-mostly) vs. Operator (volle Steuerung) als oberste Dimension | 2026-06-16 |
| 007 | Eskalations-/Meldungs-Center | temporale Achse: Reminders+Eskalationen+Fehler vereint, Kalender geht auf | 2026-06-16 |
| 008 | Repo-/Projekt-zentriert | gruppiere nach Repo (echte Arbeitseinheit) statt Entitätstyp | 2026-06-16 |
| 009 | Auftrags-Werkstatt | Compose/Queue als eigener Bau-Bereich; trennt „machen" von „beobachten" | 2026-06-16 |
| 010 | Capture-first / Funnel | Inbox als Trichter roh→geklärt→verwandelt; Telegram-Capture als Eingang | 2026-06-16 |
