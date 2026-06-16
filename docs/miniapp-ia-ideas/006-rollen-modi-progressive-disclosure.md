## Ziel

Lass die IA sich an den **Modus** des Nutzers anpassen statt allen alles auf
einmal zu zeigen. Meist will der Owner nur *schauen* (läuft alles? was kam raus?);
manchmal will er *handeln* (freigeben, Auftrag starten, neu starten). Heute zeigt
jede Seite immer beide Welten gleichzeitig → das überladene Start-Dashboard. These:
zwei Modi — **Beobachter** (ruhig, read-mostly: Status, Ergebnisse, Nutzung) und
**Operator** (volle Steuerung: Freigaben, Compose, Retry, Queue). Dieselben Daten,
unterschiedliche Offenlegung (progressive disclosure).

## IA-Konzept

**Modus-Schalter im Header** (Default beim Öffnen = Beobachter, ein Tap zu Operator):
- **Beobachter:** Fokus auf Lesen — System-Status, laufende/fertige Jobs,
  Ergebnisse, Nutzung/Analytics. Schreib-Aktionen (Approve/Reject/Retry/Compose/
  Queue) sind eingeklappt hinter einem expliziten „Aktion"-Affordance; ruhige,
  scrollarme Übersicht. Weniger sichtbare Tabs.
- **Operator:** Approvals, Compose, Retry, Queue, Reminder-Anlegen stehen vorn;
  Attention-Badges aktiv; alle Steuerelemente direkt.

Gleiche Views, gleiche Routen — nur die sichtbaren Affordances unterscheiden sich.
```
+--------------------------------------------------+
| (icon) CLAUDE ZENTRALE     [ Beobachten |Steuern ]| <- Modus-Schalter
|--------------------------------------------------|
|  BEOBACHTEN: Status ok . 1 Job laeuft . 2 fertig |
|             (Aktionen eingeklappt: "2 Freigaben  |
|              warten -> zum Steuern wechseln")     |
|  ----------------- vs ------------------          |
|  STEUERN:   [Freigabe task7831  Ja|Nein]          |
|             [+ Auftrag] [+ Reminder] [Retry 2204] |
+--------------------------------------------------+
```

**Signatur-Move:** der Modus ist die oberste Filter-Dimension — die App ist erst
ruhig (verstehen), dann auf Wunsch scharf (eingreifen); kein Catch-all mehr.

## Done-Kriterien

- [ ] `js/app.js`: Modus-State (Beobachter/Operator), persistiert (z. B. localStorage);
      Header-Schalter; Default beim Start = Beobachter.
- [ ] Views (`start.js`, `activity.js`, `todos.js`, …) lesen den Modus und blenden
      Schreib-Affordances (Approve/Reject/Retry/Compose/Queue/Reminder-Create) im
      Beobachter-Modus aus bzw. klappen sie hinter ein explizites „Aktion".
- [ ] **Funktions-Parität:** im Operator-Modus ist JEDE heutige Funktion erreichbar;
      Beobachter versteckt nur, entfernt nichts (Mapping alt→neu im PR).
- [ ] Beobachter-Hinweise sind handlungsweisend, nicht sackgassig („2 Freigaben
      warten → zum Steuern wechseln"), aktive Verben in den Operator-Buttons.
- [ ] Deep-Links funktionieren in beiden Modi (Modus optional im Link, sonst Default).
- [ ] Tests grün/erweitert; a11y: Schalter ist echtes Control mit Zustands-Announce,
      Fokus bleibt nach Moduswechsel stabil.

## Leitplanken

- Telegram-Mini-App: Schalter daumenerreichbar, safe-area; ruhiger Default.
- **Keine Funktion geht verloren** — reine Offenlegungs-Ebene über denselben Views.
- Risk-Policy: Ops-Affordances erscheinen NIE über die Bridge (auch nicht im
  Operator-Modus); Compose nur mit erlaubten Presets.
- Deep-Link-Aliases bleiben funktionsfähig.
- a11y: Modus announced, sichtbarer Fokus, reduced-motion respektiert.

## Herkunft

IA-Loop, Zyklus 3, 2026-06-16. Adressiert Ist-Schwäche #4 (Start überladen) durch
modus-basierte progressive disclosure — eine persona-/absichts-getriebene Achse,
orthogonal zu Tab-Reorg (001), Triage (002), Palette (003), Master-Detail (004)
und Chains-Pipeline (005).
