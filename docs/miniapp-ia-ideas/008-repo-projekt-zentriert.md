## Ziel

Gruppiere nach der **realen Arbeitseinheit — dem Repo/Projekt — statt nach
Entitätstyp**. Die Bridge arbeitet immer gegen ein Repo (Compose hat ein
Repo-Dropdown, Todos werden mit `--repo` gequeued, `merge-on-accept` läuft je
Base). Jobs, Chains, Artifacts und Todos tragen also alle eine Projekt-Zugehörigkeit
— aber die UI zerreißt ein Projekt über fünf typ-basierte Tabs. These: ein
**„Projekte"-erst** Modell — wähle ein Projekt, sieh dort gebündelt seine Jobs,
Abläufe, Ergebnisse, gequeuten Todos und letzte Aktivität.

## IA-Konzept

**Primär = Projekt-Liste:** Repos/Projekte mit Live-Status (läuft etwas? wartet
eine Freigabe? letzte Aktivität). Tap öffnet die **Projekt-Heimat**:
- gebündelt: aktive/letzte Jobs · Abläufe (Chains) · Ergebnisse · gequeute Todos
  — alles auf dieses Repo gefiltert, ein Kontext.
- Aktionen im Kontext: „+ Auftrag" füllt das Repo vor; Todo hier queuen.

**Global-Übersicht bleibt** (alle Projekte): für den maschinenweiten Blick
(System-Status, projektübergreifende Meldungen).

**Verknüpfungen:**
- Entitätstyp-Listen werden zu Projekt-Sektionen statt eigener Tabs; Suche/Palette
  bleiben global.
- Compose erbt das gewählte Projekt-Repo (nur erlaubte Presets — Risk-Policy).
```
+--------------------------------------------------+
| (icon) CLAUDE ZENTRALE      [ Suche... ]          |
|--------------------------------------------------|
|  PROJEKTE                                         |
|   > dual-bridge     . 1 laeuft . 1 Freigabe       |
|   > dyn-central-orch . ruht . 3 Ergebnisse        |
|   > wiki            . ruht                         |
|--------------------------------------------------|
|  (gewaehlt: dual-bridge)                          |
|   Jobs 2 | Ablaeufe 1 | Ergebnisse 4 | Todos 3    |
|   [ + Auftrag (repo vorbelegt) ]  [ + Todo ]      |
|--------------------------------------------------|
| [ Projekte ][ Global ][ Mehr ]                    |
+--------------------------------------------------+
```

**Signatur-Move:** ein Projekt ist EIN Ort — kein Tab-Hopping mehr, um zu sehen,
was an einem Repo gerade passiert.

## Done-Kriterien

- [ ] **Projekt-Gruppierung** aus den Repo-Feldern von Jobs/Chains/Artifacts/Todos
      abgeleitet; eine Projekt-Liste mit Pro-Projekt-Status.
- [ ] **Projekt-Heimat-View** aggregiert Jobs/Chains/Artifacts/Todos eines Repos in
      einem Kontext (gefiltert über vorhandene Endpunkte `/jobs`,`/chains`,
      `/artifacts`,`/todos`).
- [ ] `index.html`/`js/app.js`: „Projekte" als Einstieg + „Global"-Übersicht; Tabs/
      Aliases so verdrahtet, dass bestehende Deep-Links weiter funktionieren.
- [ ] „+ Auftrag" im Projektkontext belegt das Repo vor; Todo-Queue nutzt dasselbe
      Repo; Compose nur mit erlaubten Presets (Risk-Policy).
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; jede typ-basierte Funktion bleibt
      (jetzt projekt-gefiltert oder in „Global") erreichbar; keine Capability weg.
- [ ] Tests grün/erweitert; a11y: Projektliste tastatur-navigierbar, Status nicht
      nur per Farbe, reduced-motion.

## Leitplanken

- Telegram-Mini-App: Projektliste + Heimat scrollarm, safe-area.
- **Keine Funktion geht verloren** — Umgruppierung nach Repo, kein Feature-Cut;
  Entitäten ohne Repo landen in „Global/Sonstige".
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: Compose-Presets unverändert, kein freies kind/adapter.
- a11y: Fokus sichtbar, ARIA, reduced-motion.

## Herkunft

IA-Loop, Zyklus 4, 2026-06-16. Adressiert Ist-Schwäche #1 (Entitätstypen
zerreißen den Arbeitskontext) durch Gruppierung nach dem echten Werkstück (Repo) —
geerdet in Repo-Dropdown/`--repo`-Queue/`merge-on-accept`. Eine projekt-zentrierte
Achse, orthogonal zu allen bisherigen (Lifecycle/Triage/Palette/Detail/Chains/Modi).
