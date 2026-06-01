"""Shared pytest fixtures for the dual-bridge test suite.

Test-isolation guard for two cross-file leak classes (Wiki-TODO
2026-05-31-dual-bridge-test-isolation-leak):

1. **Env leak.** Several test files set ``DUAL_BRIDGE_*`` vars (ROOT, ENDPOINT,
   REPO_ALLOWLIST, CODEX_BIN, ...) without a teardown. bridge_common reads them
   lazily on every path/identity access, so a leaked var silently reconfigures a
   later test.

2. **Runner-registry leak (the actual root cause of the flaky
   test_poll_routes_implement_to_codex).** ``runners.RUNNERS`` starts as
   ``{"echo": run_echo}`` at import; ``codex_adapter`` / ``claude_adapter``
   register their runners as an import side effect. When a test does
   ``importlib.reload(runners)`` (test_lanes, test_gate_evidence), RUNNERS is
   reset to echo-only and codex/claude vanish. A later test that resolves
   ``adapter: codex`` then hits "unbekannter adapter: 'codex'". Reloading
   handoff_poll does NOT re-register them (the adapter modules are already in
   sys.modules, so ``import`` is a no-op for their side effects).

This autouse fixture snapshots+restores the env AND re-imports the adapter
modules so the codex/claude runners are registered before every test. Fixes the
whole leak class, not just one symptom.
"""
from __future__ import annotations

import importlib
import os

import pytest

_PREFIX = "DUAL_BRIDGE"


def _ensure_runners_registered() -> None:
    """Make sure runners.RUNNERS has echo + codex + claude registered.

    Idempotent: re-importing an already-loaded adapter module is a no-op for its
    register_runner() side effect, so if a prior test reload()ed runners (wiping
    the dict), we reload the adapter modules to re-run their registration.
    """
    import runners

    for adapter_mod, name in (("codex_adapter", "codex"), ("claude_adapter", "claude")):
        if name not in runners.RUNNERS:
            mod = importlib.import_module(adapter_mod)
            importlib.reload(mod)


@pytest.fixture(autouse=True)
def _isolate_dual_bridge_state():
    """Snapshot+restore DUAL_BRIDGE_* env and re-register runners around tests."""
    snapshot = {k: v for k, v in os.environ.items() if k.startswith(_PREFIX)}
    _ensure_runners_registered()
    try:
        yield
    finally:
        for key in [k for k in os.environ if k.startswith(_PREFIX)]:
            if key not in snapshot:
                del os.environ[key]
        for key, value in snapshot.items():
            os.environ[key] = value
        # Leave the registry healthy for the next test too.
        _ensure_runners_registered()
