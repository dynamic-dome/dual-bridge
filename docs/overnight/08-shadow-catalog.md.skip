## Ziel

Fahre den Goal-Loop nachts doppelt — einen Hauptlauf und einen identisch
konfigurierten Schattenlauf in getrennter Ablage — und gib ausschließlich die
Diff der beiden Ergebnisse aus. Eine nicht-leere Diff bei identischem Input
deckt eine versteckte Nicht-Determinismus-Quelle auf (genau die Klasse der 3
Loop-Bugs, die nur live sichtbar waren).

## Done-Kriterien

- Ein Skript `scripts/shadow_run.py` fährt denselben Seed zweimal: regulär
  (Hauptkatalog → normale Result-Ablage) und als Schatten (separate
  field-notes-/Result-Ablage), beide in isolierten throwaway-Klonen.
- Ein Diff der beiden Verdikt-/commit-Ergebnisse wird ausgegeben; leere Diff =
  Exit 0, gefüllte Diff = Exit != 0 mit lesbarer Gegenüberstellung.
- Bekannte Nicht-Determinismus-Quellen (z.B. microsecond-Timestamp-Seeds,
  Reihenfolge-Effekte) sind im Diff-Report benannt, nicht stillschweigend
  normalisiert.
- Test-Isolation gewahrt (CLAUDE.md §3): keine Production-DB, kein echtes Repo,
  kein Push.

---

## Anleitung (Schritt für Schritt)

1. **Voraussetzung:** Seed `07-test-live-mirror.md` ist grün gelaufen (Mechanik
   Test-vs-Live bewiesen). Erst dann `.skip` von dieser Datei entfernen.
2. Baue `shadow_run.py` auf der in 07 erprobten throwaway-Klon-Logik auf.
3. Starte denselben Seed zweimal in zwei getrennten Klonen mit getrennter
   Result-Ablage (Haupt vs. Schatten).
4. Vergleiche Verdikt, commit-ahead-Status und (falls vorhanden) den
   Review-Diff zwischen beiden Läufen.
5. Bei Divergenz: isoliere die Quelle (Picker-Timestamp? Adapter-Reihenfolge?
   externer State?) und dokumentiere sie.

## Erwartung / Akzeptanz

- **Leere Diff:** Determinismus des Loops bei identischem Input bewiesen — ein
  starkes Continuity-Gütesiegel.
- **Gefüllte Diff:** ein Bug der live-only-Klasse gefunden, den kein Unit-Test
  je gezeigt hätte — der eigentliche Zweck des Schattenkatalogs. Jede Divergenz
  ist ein zu untersuchender Befund.

## Aktivierung

Diese Datei trägt absichtlich `.skip` — sie ist Stufe 2 des Reifepfads und
hängt von Seed 07 ab. Sobald 07 grün ist: `git mv docs/overnight/
08-shadow-catalog.md.skip docs/overnight/08-shadow-catalog.md`.

## Herkunft

crazy-professor Single-Run 2026-06-03, `labyrinth-librarian × beehive ×
exaggeration`, Provokation #7 (Bibliothekswesen: Schattenkatalog → Diff = Bug).
Schlägt im selben Geist die alchemist-#7 mit breiterem Netz (ganzer Loop statt
ein Test). field-notes: dual-bridge `.agent-memory/lab/crazy-professor/
field-notes.md` Zeile 4 (kept). Stufe 2 von 2 des Reifepfads.
