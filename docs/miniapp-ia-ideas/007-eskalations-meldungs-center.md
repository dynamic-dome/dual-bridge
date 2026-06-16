## Ziel

Mache die **Zeit und die Meldungen** zum Rückgrat. Die Bridge eskaliert
fail-closed an den Owner (Telegram-Alert, dedupliziert je `loop_id`,
`ESCALATION-<loop_id>.md`); Reminders feuern; Jobs schlagen fehl. All das sind
**zeitliche Ereignisse** — heute aber zersplittert (Kalender-Tab für Zukunft,
Aktivität für Fehler, kein Ort für Eskalationen mit Begründung). These: EINE
Zeitachse „Meldungen", die Zukunft (Reminders), Jetzt (wartende Freigaben,
Eskalationen, Fehler) und kürzlich Erledigtes zusammenführt — mit nachvollziehbarer
Eskalations-Herkunft. Der Kalender-Tab geht darin auf.

## IA-Konzept

**Neuer Bereich „Meldungen" (ersetzt Kalender-Tab):** ein temporaler Feed in drei
Bändern:
- **Bald** — fällige/kommende Reminders mit Countdown (heutiger Kalender-Inhalt),
  Recurrence; Reminder anlegen bleibt hier.
- **Jetzt** — wartende Freigaben, **Eskalationen** (mit Link auf Ursache:
  loop_id / Job / Eskalations-Doku), fehlgeschlagene Jobs.
- **Vorhin** — kürzlich abgeschlossene/entschiedene Ereignisse (Audit-Spur).

**Header-Glocke** zeigt die Zahl ungelöster Meldungen (statt verstreuter Badges).

**Verknüpfungen:**
- Eskalation → verlinkt ihre Ursache (Loop/Job + `ESCALATION-<loop_id>.md`-Kontext),
  schließt die heutige „warum eskaliert?"-Lücke.
- Freigaben erscheinen als Meldung, Aktion läuft über die bestehenden Endpunkte.
- Reminder-Create wandert NICHT zu noch einem Entry-Point — es bleibt hier verortet.
```
+--------------------------------------------------+
| (icon) CLAUDE ZENTRALE              (bell) 3      |
|--------------------------------------------------|
|  BALD                                             |
|   in 2h   Reminder: Backup pruefen   [Erledigt]   |
|  JETZT                                            |
|   [!] Eskalation loop a1f  -> Ursache: job 7831   |
|   [~] Freigabe task2204 wartet     [Ja][Nein]     |
|   [x] Job 6600 fehlgeschlagen      [Neustart]     |
|  VORHIN                                           |
|   09:12  Job 7820 fertig . 08:40 Freigabe erteilt |
|--------------------------------------------------|
| [ Start ][ Meldungen ][ Arbeit ][ Mehr ]          |
+--------------------------------------------------+
```

**Signatur-Move:** Eskalationen werden erstklassig und erklärt — die App sagt
nicht nur „es hängt", sondern „was, warum, seit wann, was tun".

## Done-Kriterien

- [ ] Neue **Meldungen-View** führt `/reminders` + wartende Approvals +
      fehlgeschlagene Jobs + Eskalationen + kürzlich Erledigtes in einem
      temporalen Feed (Bald/Jetzt/Vorhin) zusammen.
- [ ] `index.html`/`js/app.js`: Kalender-Tab durch „Meldungen" ersetzt; Header
      bekommt einen Glocken-Indikator (Zahl ungelöster Meldungen); Aliases bleiben.
- [ ] Eskalations-Einträge verlinken ihre Ursache (loop_id/Job; Eskalations-Kontext);
      Reminder-Anlegen/Recurrence vollständig erhalten (kein Funktionsverlust).
- [ ] Freigaben als Meldung mit Aktion über bestehende `/approvals/...`-Endpunkte.
- [ ] **Funktions-Parität:** Mapping alt→neu im PR (insb. alle Kalender-Funktionen);
      `calendar.test.js` grün/migriert; a11y (Feed als Liste, Zeit nicht nur visuell).

## Leitplanken

- Telegram-Mini-App: Feed scrollbar, safe-area; Glocke daumenerreichbar.
- **Keine Funktion geht verloren** — Kalender wird verortet, nicht entfernt.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: unangetastet (Anzeige-/Verknüpfungs-Ebene; Aktionen über bekannte Pfade).
- a11y: chronologische Semantik, sichtbarer Fokus, reduced-motion.

## Herkunft

IA-Loop, Zyklus 4, 2026-06-16. Adressiert Ist-Schwäche #3 (Approvals/Eskalationen
verstreut, kein Verlauf) und #6 (Reminder-Entry-Points) über eine temporale
Achse — anders als der handlungs-zentrierte Triage-Stream (002), hier Zeit +
Eskalations-Herkunft als Ordnungsprinzip.
