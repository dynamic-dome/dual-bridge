"""Regression sweep: production subprocess spawns must stay windowless."""

from __future__ import annotations

import ast
from pathlib import Path


_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_output", "check_call"}


def _production_scripts() -> list[Path]:
    root = Path(__file__).resolve().parent
    return sorted(
        path for path in root.glob("*.py")
        if not path.name.startswith("diagnose-")
        and not path.name.startswith("test_")
        and path.name != "conftest.py"
    )


def _subprocess_call_name(node: ast.Call) -> str | None:
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "subprocess"
        and func.attr in _SUBPROCESS_CALLS
    ):
        return func.attr
    return None


def test_all_production_subprocess_spawns_declare_creationflags():
    violations: list[str] = []
    for path in _production_scripts():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            call_name = _subprocess_call_name(node)
            if call_name is None:
                continue
            kwargs = {kw.arg for kw in node.keywords if kw.arg}
            if "creationflags" not in kwargs:
                rel = path.relative_to(path.parents[1]).as_posix()
                violations.append(f"{rel}:{node.lineno} subprocess.{call_name}")

    assert violations == []
