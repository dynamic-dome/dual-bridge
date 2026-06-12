"""Suite wrapper for the Seed-07 live mirror (live_mirror.py).

Keeps the live-vs-unit mirror inside CI so a regression in the
`_commits_ahead_of_base` self-commit path (one of the three live-only loop bugs,
P012) shows up here too — not only when someone runs the script by hand.

These are deliberately thin: the real work lives in live_mirror.run_mirror().
We assert (a) the happy path agrees with the mirrored unit test (exit 0) and
(b) a negative control — neutralizing the fixed-bug path makes the mirror go red
(exit 1), proving the mirror actually discriminates and is not trivially green."""
from __future__ import annotations

import shutil

import pytest

import adapter_git as ag
import live_mirror as lm

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not on PATH"
)


def test_live_mirror_agrees_with_unit_assertion():
    """The real live path (genuine subprocess + fake-codex binary, real local
    git) reproduces the mirrored unit test's verdict → exit 0, no divergence."""
    code, line = lm.run_mirror()
    assert code == 0, line


def test_live_mirror_detects_regression(monkeypatch):
    """Negative control: if the fixed self-commit detection path regresses
    (_commits_ahead_of_base sees nothing), the adapter falls back to the pre-fix
    'no change' behaviour. The mirror MUST then report divergence (exit 1),
    otherwise it would be a green test that proves nothing (L1/P006)."""
    monkeypatch.setattr(ag, "_commits_ahead_of_base", lambda *a, **k: [])
    code, line = lm.run_mirror()
    assert code == 1, f"mirror failed to detect the regression (got exit {code}): {line}"
    assert "Divergenz" in line
