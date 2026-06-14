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
import tempfile
from pathlib import Path

import pytest

# The build-review loop clones repos (with their own test files) under
# state/work/<loop_id>/. Never collect those — they cause import-file-mismatch
# collisions with the real scripts/ tests.
collect_ignore_glob = ["state/*"]

_PREFIX = "DUAL_BRIDGE"

# The real Google-Drive bridge root. A test that resolves to this path would
# write into the shared, cross-device Drive folder — exactly the HIGHEST-PRIORITY
# isolation violation (global CLAUDE.md rule 3). We forbid it structurally.
_REAL_DRIVE_FRAGMENT = "dynamic_sharepoint"

# The real A-side loop-state dir (scripts/state/). A test that resolves
# DUAL_BRIDGE_STATE to this path would leak LOOP-*.jsonl / ESCALATION-*.md /
# work-clones into the live state dir (#7923). Forbid it structurally, same
# poison-guard pattern as the Drive root above.
_REAL_STATE_DIR = os.path.normcase(
    os.path.abspath(Path(__file__).resolve().parent / "state"))


def _assert_not_real_state(state: str) -> None:
    """Poison guard: refuse a DUAL_BRIDGE_STATE that points at scripts/state/."""
    if os.path.normcase(os.path.abspath(state)) == _REAL_STATE_DIR:
        raise RuntimeError(
            f"DUAL_BRIDGE_STATE resolves to the real loop-state dir ({state!r}). "
            "Tests must run against an isolated tmp state - refusing to proceed."
        )


def _assert_not_real_drive(root: str) -> None:
    """Poison guard: refuse a DUAL_BRIDGE_ROOT that points at the real Drive.

    Mirrors the test-DB poison-guard pattern — proving isolation by snapshot,
    not by trusting a header. Raised as RuntimeError so the test run aborts
    loudly instead of silently polluting the shared bridge folder."""
    norm = os.path.normcase(os.path.abspath(root))
    if _REAL_DRIVE_FRAGMENT in norm:
        raise RuntimeError(
            f"DUAL_BRIDGE_ROOT resolves to the real Drive ({root!r}). "
            "Tests must run against an isolated tmp root - refusing to proceed."
        )


def _ensure_runners_registered() -> None:
    """Make sure runners.RUNNERS has echo + codex + claude registered.

    Idempotent: re-importing an already-loaded adapter module is a no-op for its
    register_runner() side effect, so if a prior test reload()ed runners (wiping
    the dict), we reload the adapter modules to re-run their registration.
    """
    import runners

    for adapter_mod, name in (("codex_adapter", "codex"),
                              ("claude_adapter", "claude"),
                              ("codex_review_adapter", "codex-review")):
        if name not in runners.RUNNERS:
            mod = importlib.import_module(adapter_mod)
            importlib.reload(mod)


@pytest.fixture(autouse=True)
def _isolate_dual_bridge_state(tmp_path_factory):
    """Force an isolated bridge root, snapshot+restore DUAL_BRIDGE_* env, and
    re-register runners around every test.

    Isolation is now STRUCTURAL, not per-test discipline: every test starts with
    DUAL_BRIDGE_ROOT pointed at a fresh tmp dir. A test that needs a specific
    layout still overrides DUAL_BRIDGE_ROOT itself (the existing _fresh_bridge
    helpers) — that is fine, it just points at a different tmp. The poison guard
    runs both before and after the body so a missing/forgotten override can never
    fall back to the real Drive (bridge_common.bridge_root()'s default).
    """
    snapshot = {k: v for k, v in os.environ.items() if k.startswith(_PREFIX)}
    # Default every test to a unique isolated root BEFORE it runs.
    default_root = tmp_path_factory.mktemp("bridge-root")
    os.environ["DUAL_BRIDGE_ROOT"] = str(default_root)
    _assert_not_real_drive(os.environ["DUAL_BRIDGE_ROOT"])
    # Isolate the singleton lock too (DCO #7728). bc.default_lock_path() honors
    # DUAL_BRIDGE_LOCK; without this every test — and loop_driver's derived
    # dual-bridge-loop.lock — shared ONE system-temp lock. A leftover/parallel
    # holder with a recycled-but-live PID then made acquire_singleton_lock()
    # return False, flipping main()'s rc 2 -> 0 ("ein Loop laeuft bereits").
    # Point it at this test's own tmp dir so no run can collide with another.
    # (Cleaned up by the DUAL_BRIDGE_* snapshot/restore in the finally below.)
    lock_dir = tmp_path_factory.mktemp("bridge-lock")
    os.environ["DUAL_BRIDGE_LOCK"] = str(lock_dir / "poller.lock")
    # Force a deterministic endpoint so the suite never depends on a machine's
    # persistent `setx DUAL_BRIDGE_ENDPOINT`. Several tests assume the DEFAULT
    # node (claude@laptop-a -> lane A-to-B); a leaked codex@laptop-b flips the
    # lane and they fail spuriously (Wiki-TODO P2). A test that needs the other
    # endpoint still overrides DUAL_BRIDGE_ENDPOINT itself.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
    # Isolate config.json too. The repo now ships a real config.json at the repo
    # root, and bridge_common.default_config_path() points there by default. A
    # test asserting a hardcoded fallback (e.g. round_timeout 300) would instead
    # pick up the shipped file's value and break — and an edit to config.json
    # would silently flip suite behaviour. Point DUAL_BRIDGE_CONFIG at a
    # non-existent tmp path so config_value() falls through to its fallbacks.
    # test_bridge_config.py overrides this itself to point at a controlled file.
    os.environ["DUAL_BRIDGE_CONFIG"] = str(default_root / "no-config.json")
    # Isolate the A-side loop-state dir too (#7923). loop_driver._state_dir()
    # now reads DUAL_BRIDGE_STATE lazily; default every test to a fresh tmp so a
    # test that triggers append_state/run_*_loop can never leak LOOP-*.jsonl into
    # the live scripts/state/. A test needing a specific state dir overrides this
    # itself (the _reload_as_a / append_state helpers do exactly that).
    state_root = tmp_path_factory.mktemp("bridge-state")
    os.environ["DUAL_BRIDGE_STATE"] = str(state_root)
    _assert_not_real_state(os.environ["DUAL_BRIDGE_STATE"])
    _ensure_runners_registered()
    try:
        yield
    finally:
        # Guard against a test that overrode STATE to the real dir mid-body.
        _assert_not_real_state(os.environ.get("DUAL_BRIDGE_STATE", str(state_root)))
        # Guard against a test that overrode ROOT to the real Drive mid-body.
        current = os.environ.get("DUAL_BRIDGE_ROOT", "")
        for key in [k for k in os.environ if k.startswith(_PREFIX)]:
            if key not in snapshot:
                del os.environ[key]
        for key, value in snapshot.items():
            os.environ[key] = value
        # Leave the registry healthy for the next test too.
        _ensure_runners_registered()
        if current:
            _assert_not_real_drive(current)
