## Ziel

Spiegle einen einzelnen Regressionstest gegen seinen echten Live-Pfad: nimm
einen der Tests aus `scripts/test_loop_continuity_realgit.py`
(`test_codex_self_commit_is_seen_as_progress` ODER
`test_round2_builds_on_round1_commit`) und beweise, dass der `loop_driver`-Pfad,
den der Test simuliert, auch in einem echten, isolierten Live-Lauf dasselbe
Verhalten zeigt — nicht nur im Test-Harness.

## Done-Kriterien

- Ein Skript `scripts/live_mirror.py` (oder ein Test `test_live_mirror.py`)
  existiert, das EINEN benannten Realgit-Test auswählt und denselben Setup
  gegen den echten `loop_driver`-Codepfad in einem `tmp_path`-Klon fährt.
- Das Live-Ergebnis (Verdikt + commit-ahead-Status) wird mit der Assertion des
  gespiegelten Unit-Tests verglichen; bei Übereinstimmung Exit 0, bei Divergenz
  Exit != 0 mit lesbarem Diff.
- Der Lauf nutzt eine isolierte Test-DB/throwaway-Klon (CLAUDE.md §3 — keine
  Production-DB, kein echtes Repo).
- Ergebnis als ein Satz in `docs/live-proofs/` protokolliert: „Unit-Test X und
  Live-Pfad stimmen überein" ODER „Divergenz gefunden: <Beschreibung>".

---

## Anleitung (Schritt für Schritt, ~1 h)

1. Wähle `test_codex_self_commit_is_seen_as_progress` (Z.103 in
   `test_loop_continuity_realgit.py`) — er deckt genau die Klasse ab, die einer
   der 3 Loop-Bugs war (`_commits_ahead_of_base`).
2. Repliziere dessen `tmp_path`-Setup (echtes lokales git, kein Remote-Push) in
   `live_mirror.py`, aber statt der Test-Assertion rufst du den **echten**
   `loop_driver`-Codepfad einmal auf.
3. Vergleiche das Live-Ergebnis mit dem, was der Unit-Test behauptet.
4. Gib bei Divergenz einen Diff aus (erwartet vs. live).
5. Protokolliere den Einzeiler in `docs/live-proofs/`.

## Erwartung / Akzeptanz

- **Grün (Erfolg):** Live-Pfad bestätigt den Unit-Test → die Mechanik
  „Reaktor-grün == Wald-korrekt" ist für diesen einen Test bewiesen. Damit ist
  der Prototyp des Reifepfads fertig und Seed `08-shadow-catalog.md` (Ausbau)
  wird freigeschaltet.
- **Rot (auch wertvoll):** Live-Pfad weicht ab → eine Lücke gefunden, die der
  Unit-Test nicht sah (genau die live-only-Klasse der 3 Loop-Bugs, P012). Das
  ist KEIN Fehlschlag des Tasks, sondern sein eigentlicher Wert.

## Herkunft

crazy-professor Single-Run 2026-06-03, `systems-alchemist × feint × reversal`,
Provokation #7 (Reststoff „Test grün ≠ Live korrekt" als Haupt-Input).
Konvergenz: dieselbe Idee tauchte unabhängig in `labyrinth-librarian #6`
(Seismologie P-/S-Wellen) auf. field-notes: dual-bridge `.agent-memory/lab/
crazy-professor/field-notes.md` Zeile 3 (kept). Stufe 1 von 2 des Reifepfads.
