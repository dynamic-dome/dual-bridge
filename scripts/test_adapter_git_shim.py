"""Pin-Tests fuer die adapter_git-Extraktion (Spec 2026-06-12).

Schuetzt drei Invarianten des Refactors:
1. Shim = Alias: codex_adapter re-exportiert exakt die adapter_git-Objekte
   (kein Code-Duplikat, `is`-Identitaet).
2. Kein Rest-Plumbing: codex_adapter definiert keine eigenen git-Helfer mehr.
3. Namespace-Aufrufe: verbleibender codex-Code ruft umgezogene Helfer nur als
   `adapter_git.<name>(` auf — nackte Aufrufe wuerden Monkeypatches ins Leere
   laufen lassen (Spec-Hauptrisiko "Patches ins Leere").
"""
import re
from pathlib import Path

import adapter_git as ag
import codex_adapter as ca

_MOVED_FUNCS = [
    "_run_git", "_resolve_https_credential", "_write_askpass_wrapper",
    "_remote_default_branch", "_resolve_base_branch", "_git_clone_or_pull",
    "_diagnose_clone_failure", "_git_checkout_branch", "_git_status_porcelain",
    "_commits_ahead_of_base", "_changed_files_vs_base", "_git_commit_and_push",
    "merge_accepted_to_base", "push_branch_on_escalation", "_git_diff",
    "safe_build_branch",
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
        if stripped.startswith(("#", "import ", "from ")):
            continue
        for name in _MOVED_FUNCS:
            if re.search(rf"(?<![\w.]){re.escape(name)}\(", line):
                assert f"adapter_git.{name}(" in line, f"Zeile {lineno}: {line!r}"
