## Ziel

Mache die **Aufmerksamkeit des Operators** zum Rückgrat der App statt der
Datentypen. Die eigentliche Aufgabe der Zentrale ist: „sag mir, was JETZT eine
menschliche Entscheidung braucht" — Freigaben, Eskalationen, fehlgeschlagene
Jobs, fällige Reminders. Heute ist genau das über Start-Lanes, Aktivität-Filter
und Mehr-Karten verstreut. Neue These: **ein priorisierter Triage-Stream** (wie
Inbox-Zero) ist die Startfläche; alles andere wird zur sekundären „Stöber"-Ebene.
Ziel ist, dass der Operator die App öffnet, den Stream von oben abarbeitet und
fertig ist.

## IA-Konzept

**Primärfläche = „Posteingang der Entscheidungen" (Triage):**
Eine einzige, nach Dringlichkeit sortierte Liste heterogener „Action-Cards":
- Freigabe wartet → Annehmen / Ablehnen / Kommentar (inline, kein Tab-Sprung)
- Job fehlgeschlagen → Neu starten / Detail / Eskalation ansehen
- Reminder fällig → Erledigt / Verschieben
- Chain pausiert (paused_on_error) → Fortsetzen / Abbrechen
Jede Card trägt Swipe-/Inline-Aktionen; abgearbeitete Cards verlassen den Stream.
**Inbox-Zero-Zustand** = leere, einladende „alles erledigt"-Fläche (kein Mood,
sondern: „Nichts wartet. Neuen Auftrag starten?").

**Sekundäre Tabs (Stöbern, nicht Handeln):**
1. **Triage** (Default-Startfläche, s. o.) — mit Attention-Badge = Stream-Länge.
2. **Strom** — vollständige Aktivität (alle Jobs/Chains, auch erledigte), filterbar.
3. **Bibliothek** — Captures (Eingang) + Ergebnisse (Artifacts), das „Material".
4. **Mehr/Analyse** — Verlauf/Nutzung/Workflows (bleibt, aber deep-linkbar).

**Verknüpfungen:**
- **Approvals bekommen eine Heimat:** der Triage-Stream IST der Approval-Ort;
  Start-Lane und Mehr-Karte für Freigaben entfallen (Ende der 3-Stellen-Streuung).
- Ein **Approval-Verlauf** wird sichtbar (entschiedene Freigaben unter „Strom"
  filterbar: wer/wann), schließt die heutige Transparenz-Lücke.
- Globaler **„+"-Create** (FAB): Compose/Reminder/Todo aus jeder Fläche.
```
+--------------------------------------------------+
| (icon) CLAUDE ZENTRALE     Triage: 3 warten      |
|--------------------------------------------------|
|  [!] Freigabe: task7831 deploy  [Ja][Nein][...]  | <- Action-Card
|  [x] Job fehlgeschlagen: 2204   [Neustart][Det]  |
|  [o] Reminder faellig: Backup   [Erledigt][+1h]  |
|  ........ darunter: "alles erledigt" .........   |
|--------------------------------------------------|
| [ Triage ] [ Strom ] [ Bibliothek ] [ Mehr ] (+)| <- (+) = globaler Create
+--------------------------------------------------+
```

**Signatur-Move:** der Triage-Stream als einzige Pflicht-Fläche; Erfolg = leerer
Stream (Inbox-Zero), nicht ein volles Dashboard.

## Done-Kriterien

- [ ] Neue **Triage-View** rendert eine dringlichkeits-sortierte Liste aus
      Freigaben + fehlgeschlagenen Jobs + fälligen Reminders + pausierten Chains;
      jede Card hat inline-Aktionen (kein Tab-Sprung nötig).
- [ ] `index.html`/`js/app.js`: Triage ist Default-View; Tabs auf Triage/Strom/
      Bibliothek/Mehr; Attention-Badge zeigt Stream-Länge; bestehende Aliases leiten korrekt.
- [ ] Freigaben-Quick-Action verschwindet aus Start-Lane und Mehr-Hub (eine
      Heimat); Approve/Reject/Kommentar laufen inline über bestehende
      `/approvals/{id}/{approve|reject}`-Endpunkte.
- [ ] **Inbox-Zero-Empty-State** mit handlungsorientiertem Text + „+ Neu"-CTA
      (kein leerer Bildschirm, keine Entschuldigung).
- [ ] Globaler **„+"-Create** (Compose/Reminder/Todo) aus jeder Fläche erreichbar;
      Compose nur mit erlaubten Presets (Risk-Policy).
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; jede heutige Funktion bleibt
      erreichbar; Approval-Verlauf wird neu sichtbar (entschiedene unter „Strom").
- [ ] Bestehende JS-Tests grün bzw. angepasst; a11y-Floor (Swipe hat Tasten-Alternative).

## Leitplanken

- Telegram-Mini-App: Triage daumenfreundlich, Swipe-Aktionen mit Button-Fallback.
- **Keine Funktion geht verloren** — Umpriorisierung, kein Feature-Cut.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: Compose bietet weiterhin nur Presets.
- Empty-States geben Richtung (was tun), nicht Stimmung; aktive Verben in Buttons.
- a11y: Fokus sichtbar, ARIA-Labels, reduced-motion respektiert.

## Herkunft

IA-Loop, Zyklus 1, 2026-06-16. Adressiert Ist-Schwäche #3 (Approvals an 3 Stellen,
kein Verlauf) und #4 (Start überladen) durch ein attention-getriebenes
Triage-Paradigma — radikaler Gegenentwurf zur lebenszyklus-orientierten Idee 001.
