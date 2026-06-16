## Ziel

Hebe **Chains zu einem eigenen First-Class-Bereich** mit einer echten
Pipeline-Ansicht. Heute liegen Chains in „Aktivität" untergemischt — obwohl sie
konzeptionell etwas ganz anderes sind als Einzeljobs (eigenes Status-Modell:
planned → approved → running → paused_on_error). Ein mehrstufiger Ablauf ist eine
Pipeline, kein Listeneintrag. These: ein dedizierter „Abläufe"-Bereich, der jede
Chain als **Schritt-für-Schritt-Pipeline** mit Status je Schritt und prominentem
Fehler-Gate zeigt; „Aktivität" wird dadurch zur reinen Einzeljob-Liste.

## IA-Konzept

**Neuer Bereich „Abläufe":** Liste der Chains (Status-gefärbt), Tap öffnet die
**Pipeline-Ansicht**:
- Schritte als verkettete Stufen mit Status (geplant/freigegeben/läuft/fertig/
  Fehler-Pause); jeder Schritt verlinkt auf den zugrundeliegenden Job (Drill-in).
- **`paused_on_error`** als deutliches Gate mit „Fortsetzen / Abbrechen" inline.
- Am Ende verlinkt die Chain-Summary auf das erzeugte Artifact (Ergebnisse).

**Aktivität entlastet:** zeigt nur noch Einzeljobs + Approvals; Chains wandern
komplett nach „Abläufe" (Ende der Vermischung).

**Verknüpfungen:**
- Schritt ↔ Job ↔ Artifact bleiben verlinkt (kompatibel zu 004, falls beides läuft).
- Router: neuer Pfad `/chains` (+ `/chain/:id`); bestehende Aliases bleiben gültig.
```
+--------------------------------------------------+
| < Ablaeufe   "Recherche-Lauf"  (Fehler-Pause)    |
|--------------------------------------------------|
|  [v] Schritt 1  Sammeln     fertig   -> job 7820 |
|   |                                               |
|  [v] Schritt 2  Analyse     fertig   -> job 7825 |
|   |                                               |
|  [!] Schritt 3  Briefing    FEHLER   -> job 7831 |
|        [ Fortsetzen ]  [ Abbrechen ]              |
|   :                                               |
|  [ ] Schritt 4  Versand     geplant               |
|--------------------------------------------------|
|  Ergebnis: -> Artifact "Briefing 7831" (sobald fertig)|
+--------------------------------------------------+
```

**Signatur-Move:** die Pipeline macht den Fortschritt UND den Stillstand sichtbar
— wo hängt der Ablauf, welcher Schritt, welcher Job, welche Entscheidung fehlt.

## Done-Kriterien

- [ ] Neue **Chains-/Abläufe-View** rendert je Chain eine Schritt-Pipeline mit
      Status pro Schritt; Daten aus `/chains` (+ Schritt→Job-Verknüpfung).
- [ ] `index.html`/`js/app.js`: „Abläufe" als eigener Bereich/Route (`/chains`,
      `/chain/:id`); bestehende Aliases (`/jobs`,`/approvals`→activity) bleiben gültig.
- [ ] **`paused_on_error`-Gate** mit inline „Fortsetzen/Abbrechen" über die
      vorhandenen Chain-/Job-Endpunkte; jeder Schritt drillt zum Job-Detail.
- [ ] `js/activity.js`: Chains werden NICHT mehr in die Job-Liste gemischt
      (Aktivität = Einzeljobs + Approvals).
- [ ] Chain-Summary verlinkt auf das erzeugte Artifact (Ergebnisse).
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; alle bisherigen Chain-Aktionen
      bleiben erreichbar; Tests grün/erweitert; a11y (Pipeline tastatur-navigierbar).

## Leitplanken

- Telegram-Mini-App: Pipeline vertikal stapelbar auf 360px, safe-area.
- **Keine Funktion geht verloren** — Chains nur verlagert + besser dargestellt.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: „Fortsetzen/Abbrechen" nutzt bestehende Pfade, kein neues kind/adapter.
- a11y: Schritte als Liste/Tree mit Fokus, Status nicht nur per Farbe, reduced-motion.

## Herkunft

IA-Loop, Zyklus 3, 2026-06-16. Adressiert Ist-Schwäche #5 (Chains untergemischt,
abweichendes Status-Modell) durch einen eigenen Pipeline-Bereich. Struktureller
Fokus auf den mehrstufigen Ablauf — anders als die generische Cross-Link-Idee (004).
