## Ziel

Hebe das **Aufträge-Bauen** zu einem eigenen Werkstatt-Bereich. Heute ist die
Bridge-Compose-Form auf das Start-Dashboard gequetscht (ein Grund für dessen
Überladung), und das „Auftrag zusammenstellen" konkurriert dort mit vier
Monitoring-Lanes. These: ein dedizierter **„Werkstatt"-Bereich** — der Ort, an dem
man einen Auftrag montiert (Repo + Preset + Aufgabentext), abschickt, die Queue
sieht und letzte Aufträge als Vorlage wiederverwendet. Das trennt „Arbeit machen"
sauber von „Arbeit beobachten".

## IA-Konzept

**Neuer Bereich „Werkstatt":**
- **Auftrag montieren:** Repo (Dropdown/Custom-URL) + Preset (Bauen/Test/Review/
  Recherche/Smoke — die Risk-Policy-erlaubten kind/adapter) + Aufgabentext → „In Queue".
- **Queue/Werkbank:** gerade eingereihte und laufende Aufträge dieses Sitzungs-
  Kontexts, mit Sprung ins Job-Detail.
- **Vorlagen:** letzte Aufträge als wiederverwendbare Vorlage (1 Tap füllt die Form).
- Verlinkt ans Ergebnis (Artifact), sobald fertig.

**Start entlastet:** zeigt nur noch Monitoring (Status/Lanes); der Compose-Block
wandert ganz in die Werkstatt (Start behält höchstens einen „+ Auftrag"-Knopf,
der hierher führt).

**Verknüpfungen:**
- Einheitlicher Bau-Einstieg statt Start-Compose + verstreuter Trigger.
- Todo-Queue (`/todos/{id}/queue`) kann denselben Werkstatt-Flow nutzen.
```
+--------------------------------------------------+
| (icon) WERKSTATT                                  |
|--------------------------------------------------|
|  AUFTRAG MONTIEREN                                |
|   Repo:   [ dual-bridge        v ]                |
|   Preset: (Bauen)(Test)(Review)(Recherche)(Smoke) |
|   Aufgabe:[ ........................... ]         |
|                                  [ In Queue ]     |
|--------------------------------------------------|
|  WERKBANK   job 7831 laeuft -> Detail             |
|  VORLAGEN   "Review dual-bridge" . "Smoke"        |
|--------------------------------------------------|
| [ Start ][ Werkstatt ][ Arbeit ][ Mehr ]          |
+--------------------------------------------------+
```

**Signatur-Move:** der Auftrag ist ein montiertes Werkstück (Repo+Preset+Text), die
Werkbank zeigt, was gerade „auf der Bank liegt" — Bauen wird ein Ort, kein Beiwerk.

## Done-Kriterien

- [ ] Neuer **Werkstatt-View** mit Compose (Repo + Preset + Aufgabentext) über
      `/bridge/compose`; Queue/Werkbank aus `/jobs`; „Vorlagen" aus letzten Aufträgen.
- [ ] `index.html`/`js/app.js`: „Werkstatt" als eigener Bereich/Route; bestehende
      Aliases bleiben gültig.
- [ ] `js/start.js`: Compose-Block verlässt Start; Start behält höchstens einen
      „+ Auftrag"-Einstieg, der in die Werkstatt routet.
- [ ] Compose bietet **ausschließlich die erlaubten Presets** (Risk-Policy, kein
      freies kind/adapter); Todo-Queue kann denselben Flow nutzen.
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; jede heutige Compose-/Queue-
      Funktion bleibt erreichbar; `start.compose.test.js`/`start.bridge.test.js`
      grün bzw. migriert.
- [ ] a11y: Form-Labels, Fokusreihenfolge, Fehlertexte handlungsweisend, reduced-motion.

## Leitplanken

- Telegram-Mini-App: Form daumenfreundlich, safe-area; Presets als große Tap-Ziele.
- **Keine Funktion geht verloren** — Compose wird verortet, nicht entfernt.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: nur erlaubte Presets; Fehlertexte nennen `risk_policy:<regel>` klar.
- a11y: sichtbarer Fokus, ARIA, reduced-motion.

## Herkunft

IA-Loop, Zyklus 5, 2026-06-16. Adressiert Ist-Schwäche #4 (Start überladen durch
Compose) und #6 (verstreute Create-Trigger), indem das Aufträge-Bauen ein eigener
Werkstatt-Bereich wird. Geerdet in `/bridge/compose` + Presets; trennt „machen" von
„beobachten" — orthogonal zu allen bisherigen Achsen.
