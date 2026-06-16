# 000 — Synthese & Empfehlung (IA/UX-Umbau Miniapp)

Abschluss des IA-Loops. Bewertet die 10 Direktionen (001–010), zeigt
Kombinierbarkeit und empfiehlt ein Zielbild. Grundlage: die Ist-Architektur +
6 Ist-Schwächen in `README.md`.

## Zwei Sorten von Direktionen

Entscheidend für die Synthese: nicht alle 10 sind Alternativen. Es gibt
**Leitkonzepte** (konkurrierende oberste Ordnungsprinzipien — man wählt EINES) und
**Bausteine** (querschnittliche Schichten, die sich mit fast jedem Leitkonzept
kombinieren lassen).

| # | Direktion | Typ | adressiert | Stärke | Aufwand |
|---|-----------|-----|-----------|--------|---------|
| 001 | Lifecycle-Tabs (Heute/Eingang/Arbeit/Wissen) | **Leitkonzept** | #1,#2,#6 | hoch — fixt Kernproblem, evolutionär | mittel |
| 002 | Action-Inbox / Triage | **Leitkonzept** | #3,#4 | hoch, aber radikal; lässt sich als „Heute" einbetten | mittel |
| 003 | Command-Palette-first | **Leitkonzept ODER Baustein** | #2,#6 | als Beschleuniger stark, als alleiniges Frame riskant (mobil) | mittel |
| 004 | Master-Detail + Cross-Links | **Baustein** | #2,#5 | hoch — orthogonal, fixt Bottom-Sheet + macht Beziehungen begehbar | mittel-hoch |
| 005 | Chains-Pipeline-Bereich | **Baustein** | #5 | hoch — klarer Gewinn, lokal begrenzt | mittel |
| 006 | Rollen-Modi / Progressive Disclosure | **Baustein** | #4 | mittel — wertvoll, aber später; Doppelpflege Risiko | mittel-hoch |
| 007 | Eskalations-/Meldungs-Center | **Baustein/Bereich** | #3,#6 | hoch — Eskalations-Herkunft + Kalender-Konsolidierung | mittel |
| 008 | Repo-/Projekt-zentriert | **Leitkonzept** | #1 | hoch bei vielen Repos; sonst Overkill | hoch |
| 009 | Auftrags-Werkstatt | **Baustein/Bereich** | #4,#6 | hoch — entlastet Start, bündelt Bauen | mittel |
| 010 | Capture-first / Funnel | **Leitkonzept** | Inbox-Versanden | mittel-hoch — sehr Telegram-nah; als „Eingang" einbettbar | mittel |

## Was sich ausschließt vs. kombiniert

- **Konkurrierende Leitkonzepte (genau eines als Frame wählen):** 001 ·  002 · 003 · 008 · 010.
  Sie definieren die oberste Navigation; zwei davon gleichzeitig als Frame = Chaos.
- **Gute Nachricht:** 001 (Lifecycle-Tabs) **absorbiert die Kerne der anderen Frames**
  als Tab-Inhalte, ohne sie zu verwerfen:
  - „Heute" = der Attention-/Triage-Gedanke aus **002** (+ temporale Meldungen aus **007**).
  - „Eingang" = der Capture-Funnel aus **010**.
  - „Arbeit" = Jobs/Approvals + die Chains-Pipeline aus **005**.
  - „Wissen" = die heute versteckten Verlauf/Nutzung/Workflows.
- **Bausteine, die mit JEDEM Frame laufen:** 004 (Detail-Linking), 006 (Modi),
  003 als Header-Omnibox (statt alleiniges Frame).
- **008 (Repo-zentriert)** ist der echte *Gegenentwurf*: nur wählen, wenn die
  Repo-Achse das dominante mentale Modell ist (viele parallele Projekte). Dann wird
  008 das Frame und 001 entfällt.

## Empfohlenes Zielbild

**Leitkonzept: 001 Lifecycle-Tabs** — fixt die Kernschwäche (#1 vermischte Konzepte,
#2 versteckte Funktionen) am direktesten, ist evolutionär (4 Tabs statt 7, kein
Paradigmenbruch) und dient als Container, in den die besten anderen Ideen einrücken.

Dazu drei Bausteine:
1. **004 Master-Detail + Cross-Links** — die Navigations-/Verknüpfungs-Schicht:
   deep-linkbare Detail-Routen statt Bottom-Sheet, „Verbunden"-Leiste
   (Job↔Artifact↔Quelle↔Chain). Behebt #2 strukturell, macht Beziehungen begehbar.
2. **003 als Header-Omnibox** — persistente Suche+Aktion+Anlegen oben (nicht als
   alleiniges Frame). Hebt #2 (versteckte Suche) und #6 (Create-Entry-Points) und
   passt zur „Header-Suche", die 001 ohnehin vorsieht.
3. **005 Chains-Pipeline** — als Behandlung des „Arbeit"-Tabs: Chains bekommen ihre
   Pipeline-Ansicht (#5), statt in der Job-Liste zu versinken.

**Später (Phase 2):** 006 Rollen-Modi (ruhiger Beobachter-Default) und 007 als
ausgebautes „Heute"/Meldungs-Band mit Eskalations-Herkunft. 009 Werkstatt, falls
Compose mehr Raum braucht als ein „Eingang→Neu"-Flow hergibt.

**Begründung der Reihenfolge:** erst die Struktur (001) + die Verknüpfung (004) —
das ist das Fundament, auf dem alle Detailflows sitzen. Omnibox (003) und
Chains-Pipeline (005) sind danach lokale, risikoarme Aufwertungen. Modi/Meldungen
sind Komfort-Schichten, die ohne das Fundament wenig bringen.

## Nächster Schritt (optional)
Eine gewählte Kombination lässt sich als **relay-/goal-loop-Bridge-Task** gegen das
DCO-Repo starten — die Done-Kriterien der Einzeldateien (Funktions-Parität,
Deep-Link-Erhalt, Risk-Policy-Presets) sind dafür schon formuliert und können zu
einem Umbau-Seed zusammengezogen werden.
