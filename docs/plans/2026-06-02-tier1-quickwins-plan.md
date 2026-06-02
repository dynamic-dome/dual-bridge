# Tier-1-Quick-Wins — Implementierungsplan (dual-bridge)

*Erstellt: 2026-06-02 · Quelle: Stack-Audit-Master-Roadmap (`~/wiki/wiki/queries/2026-06-02-stack-evolution-master-roadmap.md`)*
*Repo: `C:\Users\domes\AI\dual-bridge` · Branch main @ a16c698 · Test-Isolation: vorhanden (`scripts/conftest.py` autouse `_isolate_dual_bridge_state`, tmp_path, kein echtes Drive)*

## Ziel
Drei Härtungen auf einen Rutsch, TDD (Test zuerst, dann Fix). Alle drei sind unabhängig → subagent-driven parallelisierbar, danach ein gemeinsamer Verifikations-Durchlauf + ein Commit.

---

## QW1 — Codex-JSONL-Fallback-Parser (echter latenter Bug)

**Datei:** `scripts/codex_adapter.py:29–66` (`parse_codex_output` / `_answer_from_json`)

**Bug (selbst verifiziert 2026-06-02):** `codex exec --json` emittiert NDJSON (mehrere `{…}\n{…}`-Zeilen).
In `parse_codex_output` ist `text[0] == "{"`, also greift `json.JSONDecoder().raw_decode(text)` (Z.40) und
dekodiert **nur das erste Event** (`thread.started`), Rest = "trailing junk" verworfen. Die `_answer_from_json`-
List-Branch (Z.58) wird bei NDJSON NIE erreicht (Stream ist kein JSON-Array). Antwort steckt im letzten
`item.completed` / `agent_message.text` → geht verloren. Heute maskiert durch `-o answer.txt` (Z.273), wird
aber zum stillen Antwortverlust, sobald der `-o`-Pfad je wegfällt.

**Fix:** In `parse_codex_output` vor dem single-`raw_decode` einen **NDJSON-Pfad** ergänzen:
1. Wenn `text` mehrere Zeilen hat: zeilenweise parsen, jede nicht-leere Zeile per `raw_decode` (BOM-tolerant),
   Liste der dekodierten Events sammeln. **WICHTIG (User-Ergänzung):** NDJSON nur dann als NDJSON behandeln, wenn
   das line-by-line-Parsing **mehr als ein Event** erfolgreich liefert. Sonst (0/1 Event, oder eine Zeile scheitert
   mitten im Stream) → **Fallback auf den bestehenden `raw_decode(text)`-Pfad**. Das schützt hübsch eingerücktes
   Single-JSON, das ebenfalls `\n` enthält, vor Fehlinterpretation als NDJSON.
2. Aus den Events das letzte mit Antwort-Inhalt ziehen (Keys wie `item.completed` → `text`/`agent_message`/
   `result`/`message`/`content`). Bestehende `_answer_from_json`-Key-Logik wiederverwenden/erweitern.
3. Single-Objekt- und Plain-Text-Pfad unverändert lassen (Rückwärtskompatibilität).

**Tests (`scripts/test_codex_adapter.py`, neu oder erweitern):**
- `test_parse_ndjson_multi_event_returns_last_answer` — 3-Zeilen-NDJSON (`thread.started` / `item.started` /
  `item.completed` mit echter Antwort) → liefert die Antwort aus `item.completed`, NICHT "".
- `test_parse_single_json_object_unchanged` — bestehendes Single-Objekt bleibt korrekt.
- `test_parse_pretty_printed_single_json_with_newlines` — eingerücktes Single-JSON MIT `\n` → wird NICHT als NDJSON
  fehlinterpretiert (deckt den User-Fallback ab).
- `test_parse_plain_text_unchanged` — Plain-Text bleibt korrekt.
- `test_parse_ndjson_with_trailing_hook_noise` — NDJSON + Nicht-JSON-Hook-Zeile am Ende → robust (Zeile scheitert →
  zählt nicht, aber Stream bleibt verwertbar).

**Aufwand:** ~30 Min. **Risiko:** niedrig (additiver Pfad, alte Pfade unangetastet).

---

## QW2 — PYTHONUTF8=1 zentral (ersetzt verstreute reconfigure-Hacks)

**IST:** `sys.stdout/stderr.reconfigure(encoding="utf-8")` verstreut in `bridge_common.py:23`,
`codex_adapter.py:19`, `claude_adapter.py:18`, `diagnose-*.py`, + 11 Test-Dateien. Subprozesse
(`codex_adapter.py:250`, `claude_adapter.py:114`, git-calls `codex_adapter.py:85`) erben die Host-Env wie sie ist;
`PYTHONUTF8` wird NICHT gesetzt → Kinder laufen evtl. unter cp1252.

**Fix (zwei Ebenen, nicht die reconfigure-Hacks löschen — nur ergänzen):**
1. **Eigener Prozess:** In `bridge_common.py` einen Helper `ensure_utf8_runtime()`, der (a) reconfigure macht
   (zentralisiert das bestehende Muster) und idempotent ist. Module rufen ihn statt eigener try/except-Blöcke.
   *Minimal-Variante für diesen Durchgang:* Helper anlegen + in `loop_driver.py`-`__main__` aufrufen; bestehende
   Modul-Hacks bleiben vorerst (kein Risiko-Refactor von 11 Testdateien in diesem Rutsch).
2. **Kind-Prozesse:** Beim Bau der subprocess-Env (siehe QW3-Helper) `PYTHONUTF8="1"` setzen, damit codex/claude/git
   garantiert UTF-8 laufen. → QW2 und QW3 teilen sich denselben Env-Helper.
3. **CMD-interne Tools `encoding="oem"` (User-Ergänzung, Roadmap-Dossier 4):** Wo CMD-interne Tools wie `tasklist`
   oder `chcp` per subprocess gelesen werden (Suche: `tasklist`, `text=True` ohne explizites encoding, `errors=`),
   explizit `encoding="oem"` setzen statt `errors="replace"`. `oem` ist cp850 verlustfrei (CPython #105312, eryksun);
   `replace` rät und ist nur für reine PID-Digits sicher. Fundstellen vorher greppen (`tasklist` liegt vermutlich in
   `bridge_common.py` oder einem `which`/`process`-Helper), jede gefundene Stelle umstellen.

**Tests (`scripts/test_hardening.py`):**
- `test_subprocess_env_sets_pythonutf8` — der gebaute Env hat `PYTHONUTF8 == "1"`.
- `test_ensure_utf8_runtime_idempotent` — mehrfacher Aufruf wirft nicht.
- `test_tasklist_uses_oem_encoding` — falls eine tasklist/CMD-Lesestelle existiert: sie ruft mit `encoding="oem"`
  (oder der zentrale Helper tut es). Wenn KEINE solche Stelle existiert: Test entfällt, im Report vermerken.

**Aufwand:** ~20 Min (an QW3-Helper gekoppelt). **Risiko:** niedrig.

---

## QW3 — Env-Allowlist statt os.environ.copy() (Anti-Cross-Key-Leak)

**IST:** `claude_adapter.py:73` `env = dict(os.environ)` + Denylist (`env.pop ANTHROPIC_API_KEY/AUTH_TOKEN`, Z.81–82).
`codex_adapter.py:250` subprocess.run **ohne** `env=` → erbt komplette Host-Env (inkl. evtl. `OPENAI_API_KEY`,
`GITHUB_TOKEN`). Git-calls (`codex_adapter.py:85`) ebenso.

**Fix:** Zentraler Allowlist-Helper in `bridge_common.py`:
```
def safe_subprocess_env(extra: dict | None = None) -> dict:
    """Allowlist-only env for child processes — closes cross-key leaks (OpenAI<->Anthropic)
    systematically instead of denylisting one key at a time. Sets PYTHONUTF8=1 (QW2)."""
    # APPDATA + LOCALAPPDATA sind PFLICHT (User-Ergänzung): Claude/Codex/Node-CLIs suchen ihre Auth-/Config-Daten
    # dort. Ohne sie ist der Subprozess sauber gebaut, läuft real aber UNAUTHENTIFIZIERT (P006/P007: Mechanik ≠
    # Vertragstreue — genau die Falle, die ein reiner Bau-Test nicht zeigt).
    ALLOW_EXACT = {"SYSTEMROOT","SYSTEMDRIVE","WINDIR","TEMP","TMP","HOME","HOMEDRIVE","HOMEPATH",
                   "USERPROFILE","APPDATA","LOCALAPPDATA","COMSPEC","NUMBER_OF_PROCESSORS",
                   "PROCESSOR_ARCHITECTURE","PATHEXT"}
    ALLOW_PREFIX = ("PATH","PYTHON","GIT_","LANG","LC_")  # PATH exact+casing-tolerant
    base = {k: v for k, v in os.environ.items()
            if k.upper() in ALLOW_EXACT or k.upper().startswith(ALLOW_PREFIX)}
    base["PYTHONUTF8"] = "1"
    base.pop("ANTHROPIC_API_KEY", None); base.pop("ANTHROPIC_AUTH_TOKEN", None)  # belt+braces
    if extra: base.update(extra)
    return base
```
Anwenden:
- `claude_adapter.py:73` → `env = safe_subprocess_env({"CLAUDE_CODE_DISABLE_HOOKS":"1"})` (ersetzt dict+pop, behält
  den Subscription-Login-Pfad: kein ANTHROPIC_API_KEY mehr in der Env).
- `codex_adapter.py:250` → `env=safe_subprocess_env()` ergänzen.
- git-calls `codex_adapter.py:85` → `env=safe_subprocess_env()` ergänzen.

**Achtung Allowlist-Tuning:** PATH ist Pflicht (sonst findet das Kind die Exe nicht — `shutil.which` läuft im
Parent, aber das Kind braucht PATH für sub-sub-Tools wie git in codex). Erst Allowlist bauen, dann
`test_claude_adapter`/`test_codex_*` voll laufen lassen — fehlende Var zeigt sich als Test-Rotfärbung.

**Tests (`scripts/test_hardening.py`):**
- `test_safe_env_drops_api_keys` — mit gesetztem `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` in os.environ → fehlen im Ergebnis.
- `test_safe_env_keeps_path` — `PATH` ist vorhanden und nicht leer.
- `test_safe_env_extra_overlay` — `extra`-Dict landet im Ergebnis.

**Aufwand:** ~40 Min. **Risiko:** mittel (Allowlist könnte nötige Var verfehlen → durch volle Test-Suite abgefangen).

---

## Ausführungs-Strategie (subagent-driven)

**Reihenfolge wegen geteiltem Helper:** QW3-Helper (`safe_subprocess_env`) zuerst, weil QW2 (`PYTHONUTF8`)
darauf aufsetzt. QW1 ist komplett unabhängig → echt parallel.

- **Subagent A:** QW1 (codex_adapter Parser + 4 Tests) — isoliert, parallel.
- **Subagent B:** QW3+QW2 (bridge_common Helper + ensure_utf8 + 5 Tests, dann Anwendung in claude_adapter/
  codex_adapter) — ein Strang, weil beide denselben Helper berühren.
- **Danach (Haupt-Agent):** volle Suite `python -X utf8 -m pytest -q` grün? `pytest --co -q` zählt Tests (Exit-5-
  Trap)? Dann EIN chirurgischer Commit (nur die 3 geänderten scripts + Tests, `git add` explizit — §7).

**Pflicht-Gates vor Commit:**
1. `pytest --co -q` (Exit 5 = 0 Tests → REJECT).
2. `python -X utf8 -m pytest -q` voll grün (keine Regression in den 11 Testdateien).
3. QW3: ein Test beweist, dass ein injizierter `OPENAI_API_KEY` NICHT im Subprocess-Env landet.
4. Chirurgisches Stagen (`git status --short` vorher/nachher, nur die geänderten Pfade).
