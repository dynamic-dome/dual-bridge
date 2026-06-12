# adapter_git-Extraktion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Das git-Klon/Commit/Push-Gerüst (18 Namen, Z. 183–663) aus `scripts/codex_adapter.py` verbatim in ein neues Modul `scripts/adapter_git.py` extrahieren — behavior-preserving, Suite 403→406 grün (3 neue Pin-Tests).

**Architecture:** Flaches stdlib-Modul `adapter_git.py` als Source of Truth; `codex_adapter.py` behält nur codex-Spezifisches, ruft die Helfer ausschließlich als `adapter_git.<name>(...)` auf (EIN Monkeypatch-Punkt) und re-exportiert die Namen in einer markierten Shim-Zeile. Konsumenten (`loop_driver`, 6 Testdateien) migrieren im selben Zug.

**Tech Stack:** Python stdlib, pytest. Spec: `docs/superpowers/specs/2026-06-12-adapter-git-extraction-design.md` (approved). Basis-Commit: `af1048b`.

**WICHTIGE Eigenheit dieses Refactors:** Task 2 ist EIN atomarer Umbau. Zwischen "Modul angelegt" und "Tests migriert" ist die Suite NICHT lauffähig — alte Patches auf `ca._run_git` liefen sonst ins Leere und Tests würden ECHTE git-/Netz-Aufrufe machen (z. B. `ls-remote https://x/r`). Deshalb: erst alle Schritte von Task 2 ausführen, DANN die Suite laufen lassen, dann EIN Commit. Niemals zwischendrin pytest auf die migrierten Dateien loslassen.

**Arbeitsverzeichnis:** alle Befehle aus `C:/Users/domes/AI/dual-bridge/scripts/`, Suite-Aufruf: `python -X utf8 -m pytest -q`.

---

### Task 1: Pin-Test schreiben (RED)

**Files:**
- Test (neu): `scripts/test_adapter_git_shim.py`

- [ ] **Step 1: Testdatei anlegen** — exakt dieser Inhalt:

```python
"""Pin-Tests fuer die adapter_git-Extraktion (Spec 2026-06-12).

Schuetzt drei Invarianten des Refactors:
1. Shim = Alias: codex_adapter re-exportiert exakt die adapter_git-Objekte
   (kein Code-Duplikat, `is`-Identitaet).
2. Kein Rest-Plumbing: codex_adapter definiert keine eigenen git-Helfer mehr.
3. Namespace-Aufrufe: verbleibender codex-Code ruft umgezogene Helfer nur als
   `adapter_git.<name>(` auf — nackte Aufrufe wuerden Monkeypatches ins Leere
   laufen lassen (Spec-Hauptrisiko "Patches ins Leere").
"""
from pathlib import Path

import adapter_git as ag
import codex_adapter as ca

_MOVED_FUNCS = [
    "_run_git", "_resolve_https_credential", "_write_askpass_wrapper",
    "_remote_default_branch", "_resolve_base_branch", "_git_clone_or_pull",
    "_diagnose_clone_failure", "_git_checkout_branch", "_git_status_porcelain",
    "_commits_ahead_of_base", "_changed_files_vs_base", "_git_commit_and_push",
    "merge_accepted_to_base", "push_branch_on_escalation", "_git_diff",
]
_MOVED_OTHER = ["_Cred", "_ASKPASS_HELPER", "_DIFF_LIMIT"]


def test_shim_is_alias():
    for name in _MOVED_FUNCS + _MOVED_OTHER:
        assert getattr(ca, name) is getattr(ag, name), name


def test_no_git_defs_left_in_codex_adapter():
    src = Path(ca.__file__).read_text(encoding="utf-8")
    assert "class _Cred" not in src
    for name in _MOVED_FUNCS:
        assert f"def {name}(" not in src, name


def test_remaining_calls_use_namespace():
    # Zeilenweiser Quelltext-Guard: jeder Aufruf eines umgezogenen Helfers im
    # verbleibenden codex_adapter muss adapter_git.-praefixiert sein. Import-/
    # Kommentarzeilen sind ausgenommen. (Docstrings duerfen die Namen nennen,
    # aber nicht in Aufrufform `name(` — bewusst strenger Guard.)
    src = Path(ca.__file__).read_text(encoding="utf-8")
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or "import" in line:
            continue
        for name in _MOVED_FUNCS:
            if f"{name}(" in line:
                assert f"adapter_git.{name}(" in line, f"Zeile {lineno}: {line!r}"
```

- [ ] **Step 2: RED verifizieren**

Run: `python -X utf8 -m pytest -q test_adapter_git_shim.py`
Expected: FAIL/ERROR mit `ModuleNotFoundError: No module named 'adapter_git'` (Collection-Error zählt als RED). KEIN Commit — der Commit kommt am Ende von Task 2 zusammen mit dem Refactor (Suite muss grün sein).

---

### Task 2: Atomarer Umzug (Modul + codex_adapter + loop_driver + 6 Testdateien)

**Files:**
- Create: `scripts/adapter_git.py`
- Modify: `scripts/codex_adapter.py` (Z. 168–178 Importe, Z. 183–663 Block raus, 11 Aufrufstellen Z. 837–932, Shim-Zeile)
- Modify: `scripts/loop_driver.py:20,730,809`
- Modify: `scripts/test_base_branch_resolution.py`, `test_clone_diagnose.py`, `test_escalation_push.py`, `test_loop_continuity_realgit.py:178,219,243`, `test_stage1.py:79-85`, `test_live_mirror.py:37`, `test_codex_branch_override.py:25,26,33,46,48`
- KEINE Änderung (verifiziert): `test_codex_adapter.py`, `test_pingpong_realbuild.py` (patchen nur codex-Internals)

- [ ] **Step 1: `adapter_git.py` anlegen** — Header exakt so, danach der verbatim verschobene Block:

```python
"""Shared git scaffolding for building bridge adapters (extracted 2026-06-12).

Owns the git clone/branch/commit/push dance that any BUILDING adapter needs:
credential resolution (GIT_ASKPASS, no secrets in argv/env), base-branch
resolution, workdir lifecycle, diff/status against base, commit+push, and the
merge-on-accept / escalation-push helpers used by the goal loop.

Extracted verbatim from codex_adapter.py (spec
docs/superpowers/specs/2026-06-12-adapter-git-extraction-design.md) as the
groundwork for a future claude builder. Names keep their original underscore
prefixes on purpose: minimal-diff extraction, monkeypatch targets stay stable.
codex_adapter re-exports everything as a back-compat shim. Pure stdlib.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from bridge_common import safe_subprocess_env
```

Dann: Block `codex_adapter.py` Z. 183–663 (beginnt mit `def _run_git(`, endet mit dem Ende von `def _git_diff(...)` direkt vor `def _build_codex_cmd(`) per Editor AUSSCHNEIDEN und unverändert unter den Header einfügen. Extraktion z. B.: `sed -n '183,663p' codex_adapter.py >> adapter_git.py`, danach den Block in `codex_adapter.py` löschen. Inhaltlich NICHTS ändern.

- [ ] **Step 2: Verifizieren, dass der Block vollständig und unverändert ist**

Run: `python -X utf8 -c "import adapter_git"` und `grep -c "^def \|^class " adapter_git.py`
Expected: Import ohne Fehler; 16 Definitionen (15 Funktionen + `class _Cred`). Zusätzlich enthält die Datei `_ASKPASS_HELPER = ` und `_DIFF_LIMIT = `.

- [ ] **Step 3: `codex_adapter.py` umbauen** — drei Änderungen:

(a) Im Import-Block (vorher Z. 168–178): `tempfile` und `urllib.parse` entfernen, FALLS der verbleibende Code sie nicht mehr nutzt (prüfen: `grep -n "tempfile\.\|urllib\." codex_adapter.py` — `_run_codex_exec`/`run_codex_task` nutzen sie Stand `af1048b` NICHT mehr nach dem Umzug; bei Treffern drinlassen). `os/shutil/signal/subprocess/dataclass/Path/bridge_common/runners` bleiben (codex-Pfad braucht sie).

(b) Direkt nach dem bestehenden Import-Block einfügen:

```python
import adapter_git
from adapter_git import (  # noqa: F401 — back-compat shim (Spec 2026-06-12): nur Re-Export, verbleibender Code nutzt diese Namen NICHT
    _ASKPASS_HELPER, _Cred, _DIFF_LIMIT, _changed_files_vs_base,
    _commits_ahead_of_base, _diagnose_clone_failure, _git_checkout_branch,
    _git_clone_or_pull, _git_commit_and_push, _git_diff, _git_status_porcelain,
    _remote_default_branch, _resolve_base_branch, _resolve_https_credential,
    _run_git, _write_askpass_wrapper, merge_accepted_to_base,
    push_branch_on_escalation,
)
```

(c) Die 11 Aufrufstellen in `run_codex_task` (vorher Z. 837–932) auf Namespace-Aufrufe umstellen — exakt diese Ersetzungen (alt → neu):

```
_bb_cred = _resolve_https_credential(repo)          → _bb_cred = adapter_git._resolve_https_credential(repo)
base_branch = _resolve_base_branch(...)             → base_branch = adapter_git._resolve_base_branch(...)
_git_clone_or_pull(repo, base_branch, workdir, ...) → adapter_git._git_clone_or_pull(repo, base_branch, workdir, ...)
_git_checkout_branch(workdir, branch)               → adapter_git._git_checkout_branch(workdir, branch)
changed = _git_status_porcelain(workdir)            → changed = adapter_git._git_status_porcelain(workdir)
ahead = _commits_ahead_of_base(workdir, base_branch)→ ahead = adapter_git._commits_ahead_of_base(workdir, base_branch)
diff = _git_diff(workdir, base_branch)   [2 Stellen]→ diff = adapter_git._git_diff(workdir, base_branch)
changed_files = _changed_files_vs_base(...)         → changed_files = adapter_git._changed_files_vs_base(...)
push = _run_git(workdir, "push", ...)               → push = adapter_git._run_git(workdir, "push", ...)
commit = _git_commit_and_push(workdir, branch, ...) → commit = adapter_git._git_commit_and_push(workdir, branch, ...)
```

- [ ] **Step 4: `loop_driver.py` migrieren**

Z. 20: unter `import codex_adapter  # noqa: F401` (bleibt — registriert den codex-Runner) zusätzlich `import adapter_git` einfügen.
Z. 730: `codex_adapter.merge_accepted_to_base(` → `adapter_git.merge_accepted_to_base(`
Z. 809: `codex_adapter.push_branch_on_escalation(` → `adapter_git.push_branch_on_escalation(`

- [ ] **Step 5: Reine git-Testdateien umziehen** (Patch-Ziele MÜSSEN mit, sonst Patch ins Leere → echte Netz-Calls):

`test_base_branch_resolution.py`, `test_clone_diagnose.py`, `test_escalation_push.py` — in allen drei:
- `import codex_adapter as ca` → `import adapter_git as ag`
- `from codex_adapter import _Cred` → `from adapter_git import _Cred`
- alle `ca.` → `ag.` (betrifft `monkeypatch.setattr(ca, ...)` und Direktaufrufe; die Dateien enthalten KEINE codex-spezifischen Referenzen — vorher mit `grep -n "ca\." <datei>` gegenprüfen)

- [ ] **Step 6: Gemischte Testdateien punktuell migrieren**

`test_loop_continuity_realgit.py`: `import adapter_git as ag` ergänzen; Z. 178/219/243 `ca.merge_accepted_to_base(` → `ag.merge_accepted_to_base(`. Die Patches auf `ca._run_codex_exec`/`ca.shutil` (Z. 62/63/88/89) bleiben auf `ca`.

`test_stage1.py` (im Test mit Z. 79–85): lokales `import codex_adapter as ca` durch `import adapter_git as ag` ergänzen (oder ersetzen, falls der Test sonst nichts aus `ca` nutzt — mit grep prüfen); `ca._git_clone_or_pull/_git_checkout_branch/_git_status_porcelain/_git_commit_and_push` → `ag.*`.

`test_live_mirror.py`: `import adapter_git as ag` ergänzen; Z. 37 `monkeypatch.setattr(ca, "_commits_ahead_of_base", ...)` → `monkeypatch.setattr(ag, "_commits_ahead_of_base", ...)`. Alle übrigen `ca`-Patches bleiben.

`test_codex_branch_override.py`: `import adapter_git as ag` ergänzen; NUR die Patches auf `_git_clone_or_pull`, `_git_checkout_branch`, `_git_status_porcelain` (Z. 25/26/33 und 46/48 + ggf. weitere — Datei komplett durchsehen) von `ca` auf `ag` umstellen. `ca.subprocess`, `ca._run_codex_exec`, `ca.parse_codex_output`, `ca.shutil` bleiben auf `ca`.

- [ ] **Step 7: Leeren-Patch-Sweep** — übersehene Patch-/Aufrufstellen finden:

Run: `grep -rnE "setattr\((ca|cx|codex_adapter),\s*\"(_run_git|_resolve_|_remote_|_git_|_commits_|_changed_|_write_askpass)" *.py`
Expected: KEINE Treffer mehr (alle auf `ag`/`adapter_git` migriert).

- [ ] **Step 8: Pin-Test grün verifizieren**

Run: `python -X utf8 -m pytest -q test_adapter_git_shim.py`
Expected: `3 passed`

- [ ] **Step 9: Volle Suite**

Run: `python -X utf8 -m pytest -q`
Expected: **406 passed** (403 Bestand + 3 neue Pin-Tests). Bei Abweichung: Failure-Liste gegen den Bestand diffen (gleicher Interpreter!), NICHT blind weitermachen.

- [ ] **Step 10: Commit (ein atomarer Refactor-Commit)**

```bash
git add adapter_git.py codex_adapter.py loop_driver.py test_adapter_git_shim.py \
  test_base_branch_resolution.py test_clone_diagnose.py test_escalation_push.py \
  test_loop_continuity_realgit.py test_stage1.py test_live_mirror.py \
  test_codex_branch_override.py
git status --short   # prüfen: NUR diese Dateien staged
git commit -m "refactor: git-Gerüst aus codex_adapter nach adapter_git extrahiert (Triage 1.6)

Verbatim-Umzug Z.183-663 (18 Namen), codex_adapter ruft nur noch
adapter_git.<name>() auf (ein Monkeypatch-Punkt) + Re-Export-Shim.
loop_driver + 7 Testdateien migriert, 3 Pin-Tests neu. Spec:
docs/superpowers/specs/2026-06-12-adapter-git-extraction-design.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Doku nachziehen (Soll-Zahl + CHANGELOG)

**Files:**
- Modify: `README.md:356`, `HOW-TO-USE.md:59,74`, `docs/CHANGELOG.md` (Abschnitt `## [Unreleased]`)

- [ ] **Step 1: Test-Soll-Zahl aktualisieren** — an den drei Stellen `403` → `406` (Wording drumherum unverändert; vorher per `grep -rn "403" README.md HOW-TO-USE.md` verifizieren, dass es genau diese drei Treffer sind — der CHANGELOG-`403 "error code:`-Treffer ist ein HTTP-Status, NICHT anfassen).

- [ ] **Step 2: CHANGELOG-Eintrag** unter `## [Unreleased]`, Rubrik `### Geändert` (anlegen falls fehlt):

```markdown
### Geändert
- **git-Gerüst in eigenes Modul extrahiert (`scripts/adapter_git.py`)** — Klon/
  Credential/Branch/Diff/Commit/Push-Helfer + `merge_accepted_to_base`/
  `push_branch_on_escalation` verbatim aus `codex_adapter.py` (Triage 1.6,
  Vorstufe claude-Builder). `codex_adapter` re-exportiert als Shim und ruft nur
  noch über den `adapter_git.`-Namespace auf (ein Monkeypatch-Punkt, Pin-Tests
  in `test_adapter_git_shim.py`). Suite 403 → 406.
```

- [ ] **Step 3: Konsistenz-Check + Suite-Schnelllauf**

Run: `grep -rn "406" README.md HOW-TO-USE.md | wc -l` → Expected: `3`. Danach `python -X utf8 -m pytest -q` → Expected: `406 passed`.

- [ ] **Step 4: Commit**

```bash
git add README.md HOW-TO-USE.md docs/CHANGELOG.md
git commit -m "docs: Soll-Zahl 406 + CHANGELOG-Eintrag adapter_git-Extraktion

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
