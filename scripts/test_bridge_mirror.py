"""Tests fuer den b1 Ops-State-Mirror (Loop-Host -> Drive).

Der Mirror spiegelt A-seitigen, lokal-only Loop-State (LOOP-*.jsonl,
ESCALATION-*.md, _overnight/runs, _notify) read-only in einen Drive-Unterordner,
damit die DCO-Ops-Konsole (anderer Knoten) ihn lesen kann. Schreibt NUR in den
Mirror, nie in den Source-State; entfernt im Mirror aber aufgeloeste Eintraege.
"""
from __future__ import annotations

import json

import bridge_mirror


def _seed_state(state_dir):
    (state_dir / "LOOP-loop-1.jsonl").write_text(
        json.dumps({"round": 1, "verdict": "accepted"}) + "\n", encoding="utf-8")
    (state_dir / "ESCALATION-loop-2.md").write_text(
        "---\nloop_id: loop-2\ntrigger: saturation\n---\n## Grund\nx\n",
        encoding="utf-8")
    runs = state_dir / "_overnight" / "runs"
    runs.mkdir(parents=True)
    (runs / "2026-06-16.json").write_text(json.dumps({"seeds": 2}), encoding="utf-8")
    notify = state_dir / "_notify"
    notify.mkdir(parents=True)
    (notify / "sent.json").write_text(json.dumps({"loop-2": "h"}), encoding="utf-8")


def test_mirror_copies_loop_escalation_overnight_notify(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mirror = tmp_path / "mirror"
    _seed_state(state)

    summary = bridge_mirror.mirror_state(state, mirror)

    assert (mirror / "LOOP-loop-1.jsonl").is_file()
    assert (mirror / "ESCALATION-loop-2.md").is_file()
    assert (mirror / "_overnight" / "runs" / "2026-06-16.json").is_file()
    assert (mirror / "_notify" / "sent.json").is_file()
    assert summary["copied"] == 4


def test_mirror_is_read_only_on_source(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mirror = tmp_path / "mirror"
    _seed_state(state)

    bridge_mirror.mirror_state(state, mirror)

    # Source bleibt unangetastet.
    assert (state / "LOOP-loop-1.jsonl").is_file()
    assert (state / "ESCALATION-loop-2.md").is_file()


def test_mirror_prunes_resolved_entries(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    # Eine im Mirror veraltete Eskalation, die es in der Source nicht (mehr) gibt.
    (mirror / "ESCALATION-loop-OLD.md").write_text("---\nloop_id: loop-OLD\n---\n",
                                                   encoding="utf-8")
    _seed_state(state)

    summary = bridge_mirror.mirror_state(state, mirror)

    assert not (mirror / "ESCALATION-loop-OLD.md").exists()
    assert summary["pruned"] == 1


def test_mirror_refuses_overlapping_state_and_mirror(tmp_path):
    """Codex-Fix: mirror_root darf nicht state_dir (oder Eltern/Kind) sein —
    sonst koennte der Prune Source-Dateien loeschen."""
    import pytest
    state = tmp_path / "state"
    state.mkdir()
    _seed_state(state)
    with pytest.raises(ValueError):
        bridge_mirror.mirror_state(state, state)
    # Source unangetastet.
    assert (state / "LOOP-loop-1.jsonl").is_file()


def test_mirror_dry_run_writes_nothing(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    mirror = tmp_path / "mirror"
    _seed_state(state)

    summary = bridge_mirror.mirror_state(state, mirror, dry_run=True)

    assert summary["copied"] == 0
    assert summary["dry_run"] is True
    assert not mirror.exists() or not any(mirror.iterdir())
