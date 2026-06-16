## Ziel

Mache die **Beziehungen zwischen den Objekten** zur tragenden Struktur. Heute
öffnet alles im selben transienten `#detail-overlay`, und die echten Zusammenhänge
— ein Job erzeugt ein Artifact, das Quellen zitiert und zu einer Chain gehört —
sind unsichtbar und nicht traversierbar. These: ersetze das Bottom-Sheet/Overlay
durch **deep-linkbare Detail-Routen mit einer „Verbunden"-Leiste**, sodass man von
Job → Artifact → Quelle → Chain navigieren kann. Das behebt zugleich die
nicht-deep-linkbare Mehr-Navigation.

## IA-Konzept

**Detail wird zur Route, nicht zum Overlay:** jede Entität hat eine eigene,
deep-linkbare Adresse (Browser-Back funktioniert). Jede Detail-Route zeigt:
- die Entität selbst (wie heute) PLUS
- eine **„Verbunden"-Leiste** mit navigierbaren Links zu zusammenhängenden Objekten
- einen **Pfad-Breadcrumb** des bisher gelaufenen Wegs.

**Beispiel-Traversierung:** Job 7831 → erzeugtes Artifact „Briefing" → dessen
Quellen (3) → übergeordnete Chain → andere Schritte der Chain.

**Layout:** breit = Master-Detail-Two-Pane (Liste links, Detail rechts);
schmal (Telegram-Standard) = gestapelt mit Zurück. Tabs bleiben als Einstiegs-
Listen; nur die Detail-Navigation wird vereinheitlicht und verlinkt.

**Verknüpfungen:**
- Mehr-Bottom-Sheet entfällt: Verlauf/Nutzung/Workflows werden ebenfalls Routen.
- Chains werden traversierbar (Schwäche #5): Schritt ↔ Job ↔ Artifact verlinkt.
```
+--------------------------------------------------+
| < zurueck   Job 7831  (abgeschlossen)            |
|--------------------------------------------------|
|  Pfad: Strom > Job 7831                           |
|  ...Job-Status / Output / Logs / Retry...         |
|--------------------------------------------------|
|  VERBUNDEN                                        |
|   -> Artifact "Briefing 7831"   (erzeugt)         |
|   -> Chain "Recherche-Lauf"     (Teil von)        |
|   -> Capture "URL..."           (Quelle)          |
+--------------------------------------------------+
   Tap "Artifact" -> Artifact-Route -> dessen Quellen + Chain
```

**Signatur-Move:** die „Verbunden"-Leiste — Objekte hören auf, Sackgassen zu sein;
jeder Job/Artifact/Chain ist ein Knoten in einem begehbaren Graphen.

## Done-Kriterien

- [ ] `js/app.js`: Detail-Ansichten werden deep-linkbare Routen (z. B.
      `/job/:id`, `/artifact/:id`, `/chain/:id`, `/capture/:id`) mit Browser-Back;
      bestehende Aliases bleiben gültig.
- [ ] Jede Detail-Route rendert eine **„Verbunden"-Leiste** mit funktionierenden
      Links zu zusammenhängenden Entitäten (Job↔Artifact↔Quelle↔Chain), gespeist
      aus vorhandenen Endpunkten (`/jobs`,`/artifacts`,`/chains`,`/captures`).
- [ ] `#detail-overlay` wird durch die Routen ersetzt ODER auf breiten Viewports
      als Two-Pane (Liste+Detail) dargestellt; schmal = gestapelt mit Zurück.
- [ ] Mehr-Sub-Views (Verlauf/Nutzung/Workflows) sind ebenfalls Routen statt
      Bottom-Sheet; ein Chain-Detail verlinkt seine Schritte/Jobs.
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; alle bisherigen Detail-Inhalte
      (Approve/Reject/Retry/Duett etc.) bleiben in der Route erreichbar.
- [ ] Tests grün/erweitert; a11y: Fokus springt bei Routenwechsel sinnvoll, Links
      sind echte Links (Tastatur), reduced-motion respektiert.

## Leitplanken

- Telegram-Mini-App: schmal gestapelt, Two-Pane nur ab Breakpoint; safe-area.
- **Keine Funktion geht verloren** — Detail-Aktionen vollständig erhalten.
- Deep-Links: neue Routen + alte Aliases funktionieren beide.
- Risk-Policy: unangetastet (reine Navigations-/Verknüpfungs-Ebene).
- a11y: Routen-Fokus-Management, echte `<a>`-Links, sichtbarer Fokus.

## Herkunft

IA-Loop, Zyklus 2, 2026-06-16. Adressiert Ist-Schwäche #2 (Bottom-Sheet nicht
deep-linkbar) und die unsichtbaren Cross-Links + #5 (Chains untergemischt/nicht
traversierbar). Beziehungs-getrieben — orthogonal zu Tab-Reorg (001),
Triage (002) und Eingabe-Modell (003).
