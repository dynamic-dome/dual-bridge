"""Insert 3 sequenzielle Dual-Bridge-Bau-Tasks in die DCO-Queue.

Auswahl + Reihenfolge vom User bestaetigt 2026-06-06:
  Parent: "Dual-Bridge Bau-Serie (3 Tasks, sequenziell)"
    1. Skill-Index mit Gate-Extraktion           (M  — warmlaufen)
    2. Bridge-Job-Replay & Determinismus-Harness  (L  — fordert Verdikt-Mechanik)
    3. Living Bridge/Plugin Knowledge Graph v1     (XL — nutzt Task 1 als Input)

Kriterium: sinnvoll + machbar + fordernd. Jede Spec hat Scope/Akzeptanz/Verifikation
und "nicht tun"-Regeln, damit ein Bridge-Agent sie autonom abarbeiten kann.
Erhoehter Runden-Timeout ausdruecklich erlaubt.
"""
import sys
sys.path.insert(0, r"C:\Users\domes\dynamic_central_orchestrator")
import todos

CHAT_ID = 8630776278
TAG = "projekt"

PARENT_TEXT = (
    "[DUAL-BRIDGE BAU-SERIE] 3 sequenzielle Bau-Tasks fuer die Dual-Bridge "
    "(codex baut -> claude reviewt -> reseed/verify). Reihenfolge fix: 1 -> 2 -> 3. "
    "Task 1 erzeugt einen Skill-Index, den Task 3 als Input wiederverwendet. "
    "Ziel-Repos (je 1 pro Task, privat, dynamic-dome): "
    "T1 https://github.com/dynamic-dome/skill-index.git | "
    "T2 https://github.com/dynamic-dome/bridge-replay.git | "
    "T3 https://github.com/dynamic-dome/plugin-knowledge-graph.git . "
    "Bridge-Infra-Referenz (NUR lesen, nicht reinbauen): C:/Users/domes/AI/dual-bridge "
    "= https://github.com/dynamic-dome/dual-bridge.git . Erhoehter Runden-Timeout erlaubt. "
    "Keine Auto-DB-Writes in irgendeiner v1. Tests gegen ECHTE Dateien, keine ASCII-Fixtures "
    "(globale Regel 17). Test-DB-Isolation pruefen falls ein Task pytest faehrt (Regel 3)."
)

TASK1 = """[1/3 — Skill-Index mit Gate-Extraktion] (M)
ZIEL-REPO: https://github.com/dynamic-dome/skill-index.git (privat) — hier rein bauen, klonen+pushen.
ZIEL: Python-Tool, das alle SKILL.md unter den bekannten Skill-Roots einliest und einen
durchsuchbaren Index (skill-index.json + SKILL-INDEX.md) baut.
SCOPE erlaubt: ~/.claude/skills, ~/.claude/plugins/*/skills, Plugin-Caches; rekursives SKILL.md-Finden.
NICHT erlaubt: Skill-Dateien veraendern; Netzwerk; Auto-DB-Write.
PFLICHT-TWIST (das Fordernde): harte Gates regex-robust extrahieren — MUST, Do NOT, HARD-GATE,
STOP, EXTREMELY-IMPORTANT — und pro Skill als eigene Liste fuehren. Dubletten ueber mehrere
Roots clustern (gleicher name: -> behalten/merge/archiv-Empfehlung).
PRO SKILL extrahieren: name, description, trigger-phrases, harte gates, benoetigte tools,
output-erwartung, quellpfad.
AKZEPTANZ: (a) alle lokal vorhandenen SKILL.md erkannt; (b) Gates sichtbar hervorgehoben;
(c) Dubletten-Sektion vorhanden; (d) wiederholbar, ueberschreibt nur eigene Outputs;
(e) Windows-Pfade sicher (keine POSIX-Annahmen).
VERIFIKATION: Test gegen ECHTE Skill-Dateien (Regel 17, keine ASCII-Fixtures); Stichprobe
3 Skills manuell gegen Quelle pruefen; Gate-Count > 0 fuer mind. einen superpowers-Skill.
OUTPUT: skill-index.json, SKILL-INDEX.md, kurzer Run-Report (Anzahl Skills/Gates/Dubletten)."""

TASK2 = """[2/3 — Bridge-Job-Replay & Determinismus-Harness] (L)
ZIEL-REPO: https://github.com/dynamic-dome/bridge-replay.git (privat) — hier rein bauen, klonen+pushen.
ZIEL: Tool, das einen ABGESCHLOSSENEN Bridge-Lauf aus den Job-Artefakten / rollout-*.jsonl
deterministisch nachspielt und prueft, ob derselbe Input dieselben Verdikt-/Reseed-Entscheidungen
produziert (Regressionsschutz fuer die Loop-Logik).
KONTEXT: scripts/loop_driver.py, claude_adapter.py, codex_adapter.py; parse_verdict-Logik.
Memory-Bezug: Fakes mit Wunschwerten verstecken Bugs (feedback_fake_vs_real_verdict_loops);
mode:real|fake-Trennung (reference_proof_artifact_mode_separation).
SCOPE erlaubt: lesen der bestehenden Lauf-Artefakte; reine Replay-/Vergleichslogik; Tests.
NICHT erlaubt: echte codex/claude-Subprozesse starten (Replay ist offline!); Artefakte ueberschreiben.
PFLICHT (das Fordernde): den LEERWERT-Pfad von parse_verdict explizit testen (Produktion liefert
leere reasons — Pattern P012), NICHT nur die Happy-Path-Verdikte. Ein erwartetes Reject/Escalate
im Replay muss als solches erkannt werden, nicht als Fehler.
AKZEPTANZ: (a) ein realer abgeschlossener Lauf wird byte-stabil nachgespielt; (b) Divergenz
(Replay != Original-Entscheidung) wird als FAIL gemeldet mit Diff; (c) Leerwert-/Reject-Pfad
abgedeckt; (d) klare Trennung real-Artefakt vs. Replay-Output.
VERIFIKATION: gegen einen ECHTEN gespeicherten Lauf laufen lassen (nicht erfunden); bewusst eine
Entscheidung im Replay-Input mutieren und pruefen, dass das Harness FAIL meldet (Negativ-Test).
OUTPUT: replay_harness.py + Tests, Replay-Report eines echten Laufs, Doku der Determinismus-Annahmen."""

TASK3 = """[3/3 — Living Bridge/Plugin Knowledge Graph v1] (XL)
ZIEL-REPO: https://github.com/dynamic-dome/plugin-knowledge-graph.git (privat) — hier rein bauen, klonen+pushen.
INPUT VON TASK 1: skill-index.json aus https://github.com/dynamic-dome/skill-index.git wiederverwenden.
ZIEL: Lebender Graph ueber Plugins, Skills, MCP-Tools, Pfade und Ueberschneidungen.
Beantwortet: welcher Agent/Skill fuer welchen Use Case. NUTZT skill-index.json aus Task 1 als Input.
SCOPE v1 scharf begrenzt: nur plugin-knowledge-graph.md + plugin-knowledge-graph.json (+ optional
Mermaid). KEINE Web-UI. Harte Begrenzung der Knotenzahl (sonst explodiert der Graph).
KNOTEN: plugin, skill, mcp-tool, command, pfad, use-case, gate. KANTEN: enthaelt, nutzt,
ueberschneidet-sich, blockiert-ohne-gate, routet-zu-rolle.
NICHT erlaubt: UI bauen; Task 1 neu implementieren (dessen Output konsumieren!); Auto-DB-Write.
PFLICHT (das Fordernde): Use-Cases aus Skill-descriptions ABLEITEN (nicht hartkodieren); Dubletten
aus Task 1 in den Graph uebernehmen; inkrementell regenerierbar (Re-Run aendert nur Geaendertes).
AKZEPTANZ: (a) Plugins+Skills+lokale Pfade sauber indexiert; (b) mind. 5 der Beispielabfragen
beantwortbar (z.B. "welche skills haben harte gates?", "welche skills ueberschneiden sich?");
(c) Dubletten erkannt; (d) maschinenlesbar (JSON) UND scanbar (MD); (e) reproduzierbar.
VERIFIKATION: 5 Beispielabfragen manuell gegen den Graphen pruefen; Gate-Knoten gegen Task-1-Index
cross-checken; Re-Run-Idempotenz zeigen (zweiter Lauf -> minimaler Diff).
OUTPUT: graph_builder.py, plugin-knowledge-graph.{md,json}, Query-Beispiele, Run-Report."""

def main():
    parent_id = todos.add(CHAT_ID, PARENT_TEXT, tag=TAG)
    print(f"PARENT -> DCO #{parent_id}")
    for label, text in (("T1", TASK1), ("T2", TASK2), ("T3", TASK3)):
        tid = todos.add(CHAT_ID, text, parent_id=parent_id, tag=TAG)
        print(f"{label} -> DCO #{tid} (parent #{parent_id})")

if __name__ == "__main__":
    main()
