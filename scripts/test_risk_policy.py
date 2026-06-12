"""Risk-Level-Mapping tests (spec 2026-06-12-risk-level-mapping-design.md).
Pure stdlib + assert: python -X utf8 -m pytest test_risk_policy.py -q
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path


# --- R1: Level-Mismatch (kind-Level != adapter-Capability) -------------------

def test_allowed_combos_pass() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # alle produktiven Kombinationen (Spec §Betriebsauswirkung)
    for kind, adapter in [("echo", "echo"), ("implement", "codex"),
                          ("test", "codex"), ("review", "claude"),
                          ("research", "claude"), ("research", "echo"),
                          ("implement", "increment")]:
        v = rp.check_task(kind, adapter, "## Ziel\nbau das Feature\n")
        assert v is None, f"{kind}/{adapter} muss erlaubt sein, got {v}"


def test_level_mismatch_rejected_both_directions() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # bauender Adapter auf read-Task (Eskalation)
    v = rp.check_task("review", "codex", "review the diff")
    assert v is not None and v.rule == "level-mismatch", v
    # read-Adapter auf build-Task (heutiges Spaet-Leise-Scheitern)
    v = rp.check_task("implement", "claude", "baue X")
    assert v is not None and v.rule == "level-mismatch", v
    # Begruendung nennt beide Seiten
    assert "implement" in v.reason and "claude" in v.reason


# --- R2: Ops-Verben im Auftragstext ------------------------------------------

def test_ops_verbs_rejected() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    ops_texts = [
        "registriere via schtasks /create einen Task",
        "fuehre Register-ScheduledTask aus",
        "Unregister-ScheduledTask -TaskName X",
        "git push origin main am Ende",
        "merge den Branch am Ende nach master",
        "nutze die ADMIN_PIN aus der Config",
        "/admin status",
    ]
    for text in ops_texts:
        v = rp.check_task("implement", "codex", text)
        assert v is not None and v.rule == "ops-verb", f"{text!r}: {v}"
        # Begruendung nennt das Pattern, aber niemals mehr als den Treffer
        assert v.reason, text


def test_harmless_texts_pass() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    ok_texts = [
        "review the scheduler docs",                       # kein Ops-Verb
        "pushe auf den bridge/task-Branch",                # kein Base-Push
        "git push origin bridge/loop-123",                 # Branch-Push ok
        "der Admin sieht das Dashboard",                   # 'admin' mitten im Wort/Satz
        "schreibe Tests fuer den task scheduler",
    ]
    for text in ok_texts:
        v = rp.check_task("implement", "codex", text)
        assert v is None, f"{text!r} darf nicht matchen: {v}"


def test_ops_scan_also_on_read_tasks() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # R2 gilt unabhaengig vom Level — auch ein read-Task darf keine Ops anweisen
    v = rp.check_task("review", "claude", "und danach git push origin master")
    assert v is not None and v.rule == "ops-verb", v


# --- R3: fail-closed bei Drift/kaputten Eingaben ------------------------------

def test_unknown_values_fail_closed() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    for kind, adapter in [("deploy", "codex"), ("implement", "gemini"),
                          ("", "echo"), ("echo", ""), (None, "echo"),
                          ("echo", None)]:
        v = rp.check_task(kind, adapter, "x")
        assert v is not None and v.rule == "unknown-field", f"{kind}/{adapter}: {v}"


def test_none_body_is_safe() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    assert rp.check_task("echo", "echo", None) is None
    assert rp.check_task("echo", "echo", "") is None


# --- Tabellen-Invarianten ------------------------------------------------------

def test_tables_cover_levels() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    assert rp.LEVELS == ("read", "build", "ops")
    # kein kind erreicht ops — 'kein Admin-Exec ueber die Bridge' strukturell
    assert "ops" not in rp.KIND_LEVEL.values()
    assert "ops" not in rp.ADAPTER_CAPABILITY.values()
    assert set(rp.KIND_LEVEL.values()) <= set(rp.LEVELS)
    assert set(rp.ADAPTER_CAPABILITY.values()) <= set(rp.LEVELS)


# --- loop_driver-Etikett: bauende Runden-Tasks tragen kind=implement ----------

def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    """Isolierte Bridge-Env (tmp root + endpoint) setzen. Der CALLER muss
    danach bridge_common (und davon abhaengige Module) per importlib.reload
    frisch laden und bc.ensure_dirs() rufen — sonst zeigt der Modul-State noch
    auf das Root des vorherigen Tests. Env-Restore macht die autouse-Fixture."""
    root = Path(tempfile.mkdtemp(prefix="bridge-rp-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_write_round_task_kind_follows_repo() -> None:
    _fresh_bridge()
    import bridge_common as bc; importlib.reload(bc)
    import loop_driver as ld; importlib.reload(ld)
    bc.ensure_dirs()
    lane = bc.send_lane()
    # bauender Runden-Task (repo gesetzt) -> implement
    tid = ld.write_round_task("loop-x", 1, "bau weiter", adapter="codex",
                              repo="https://github.com/dynamic-dome/dual-bridge",
                              base_branch="main", loop_branch="bridge/loop-x")
    fm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_outbox(lane) / f"task-{tid}.md"))
    assert fm["kind"] == "implement", fm["kind"]
    # Text-Runde (kein repo) -> echo wie bisher
    tid2 = ld.write_round_task("loop-y", 1, "zaehle hoch", adapter="echo")
    fm2, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_outbox(lane) / f"task-{tid2}.md"))
    assert fm2["kind"] == "echo", fm2["kind"]
    # beide Kombos sind policy-konform (Ping-Pong darf nicht brechen)
    import risk_policy as rp; importlib.reload(rp)
    assert rp.check_task(fm["kind"], "codex", "x") is None
    assert rp.check_task(fm2["kind"], "echo", "x") is None


# --- handoff_write: Sender-Gate (kein Override) --------------------------------

def test_handoff_write_rejects_mismatch_and_ops() -> None:
    _fresh_bridge()
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    bc.ensure_dirs()
    lane = bc.send_lane()
    # Level-Mismatch: review+codex -> rc 3, nichts geschrieben
    rc = hw.main(["review den diff", "--kind", "review", "--adapter", "codex"])
    assert rc == 3, rc
    assert not list(bc.lane_outbox(lane).glob("task-*.md"))
    # Ops-Verb -> rc 3, nichts geschrieben
    rc = hw.main(["git push origin main bitte", "--kind", "implement",
                  "--adapter", "codex"])
    assert rc == 3, rc
    assert not list(bc.lane_outbox(lane).glob("task-*.md"))
    # erlaubte Kombination schreibt weiterhin (rc 0)
    rc = hw.main(["spiegel mich", "--kind", "echo", "--adapter", "echo"])
    assert rc == 0, rc
    assert len(list(bc.lane_outbox(lane).glob("task-*.md"))) == 1


def test_handoff_write_choices_match_policy_tables() -> None:
    import handoff_write as hw; importlib.reload(hw)
    import risk_policy as rp; importlib.reload(rp)
    # Drift-Test (Spec §Tests Nr. 6): neue kinds/adapters ohne Policy-Eintrag
    # machen die Suite rot.
    assert hw.KIND_CHOICES == sorted(rp.KIND_LEVEL)
    assert hw.ADAPTER_CHOICES == sorted(rp.ADAPTER_CAPABILITY)
