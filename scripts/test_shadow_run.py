"""Tests for scripts/shadow_run.py.

The shadow runner must stay hermetic in tests: injected run functions stand in
for the live goal-loop, and repo factories return local throwaway paths. No test
starts Codex, reaches a network remote, or pushes to the project origin.
"""
from __future__ import annotations

import io
from pathlib import Path


SEED = """## Ziel
Build a tiny deterministic feature.

## Done-Kriterien
- Criterion A
"""


def test_shadow_pair_uses_two_separate_roots_and_empty_diff(tmp_path):
    import shadow_run as sr

    seen = []

    def repo_factory(*, source_repo: Path, run_root: Path, label: str,
                     base_branch: str) -> str:
        repo = run_root / f"{label}-origin.git"
        repo.mkdir(parents=True)
        return str(repo)

    def run_once(ctx: sr.ShadowContext) -> dict:
        seen.append(ctx)
        return {
            "loop_id": ctx.loop_id,
            "rounds_done": 1,
            "accepted": True,
            "escalated": False,
            "escalation_trigger": "",
            "final_commit": "abc1234",
            "final_branch": f"bridge/{ctx.loop_id}",
        }

    result = sr.run_shadow_pair(
        seed_text=SEED,
        source_repo=tmp_path / "source",
        work_root=tmp_path / "shadow-work",
        max_rounds=2,
        round_timeout=3,
        repo_factory=repo_factory,
        run_once_fn=run_once,
    )

    assert sr.render_diff(result) == ""
    assert [ctx.label for ctx in seen] == ["main", "shadow"]
    assert seen[0].bridge_root != seen[1].bridge_root
    assert seen[0].state_dir != seen[1].state_dir
    assert seen[0].repo != seen[1].repo
    assert (seen[0].result_dir / "result.json").exists()
    assert (seen[1].field_notes_dir / "result.json").exists()


def test_non_empty_diff_reports_commit_divergence_and_known_sources(tmp_path):
    import shadow_run as sr

    commits = {"main": "aaa1111", "shadow": "bbb2222"}

    def run_once(ctx: sr.ShadowContext) -> dict:
        return {
            "loop_id": ctx.loop_id,
            "rounds_done": 1,
            "accepted": True,
            "escalated": False,
            "escalation_trigger": "",
            "final_commit": commits[ctx.label],
            "final_branch": f"bridge/{ctx.loop_id}",
        }

    result = sr.run_shadow_pair(
        seed_text=SEED,
        source_repo=tmp_path / "source",
        work_root=tmp_path / "shadow-work",
        max_rounds=2,
        round_timeout=3,
        repo_factory=lambda **kw: str(kw["run_root"] / "origin.git"),
        run_once_fn=run_once,
    )

    diff = sr.render_diff(result)
    assert "--- main" in diff and "+++ shadow" in diff
    assert "aaa1111" in diff and "bbb2222" in diff
    assert "git commit timestamps" in diff
    assert "microsecond/uuid task ids" in diff
    assert result.has_diff is True


def test_main_prints_only_diff_and_maps_exit_code(tmp_path):
    import shadow_run as sr

    def run_once(ctx: sr.ShadowContext) -> dict:
        commit = "same000" if ctx.label == "main" else "diff999"
        return {
            "loop_id": ctx.loop_id,
            "rounds_done": 1,
            "accepted": True,
            "escalated": False,
            "escalation_trigger": "",
            "final_commit": commit,
            "final_branch": f"bridge/{ctx.loop_id}",
        }

    seed_file = tmp_path / "seed.md"
    seed_file.write_text(SEED, encoding="utf-8")
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    out = io.StringIO()

    rc = sr.main(
        [
            "--seed-file", str(seed_file),
            "--source-repo", str(source_repo),
            "--work-root", str(tmp_path / "work"),
            "--max-rounds", "1",
            "--round-timeout", "1",
        ],
        run_once_fn=run_once,
        repo_factory=lambda **kw: str(kw["run_root"] / "origin.git"),
        stdout=out,
    )

    text = out.getvalue()
    assert rc == 1
    assert text.startswith("--- main\n+++ shadow\n"), text
    assert "[shadow]" not in text
    assert "same000" in text and "diff999" in text


def test_main_prints_nothing_when_diff_is_empty(tmp_path):
    import shadow_run as sr

    def run_once(ctx: sr.ShadowContext) -> dict:
        return {
            "loop_id": ctx.loop_id,
            "rounds_done": 1,
            "accepted": True,
            "escalated": False,
            "escalation_trigger": "",
            "final_commit": "same000",
            "final_branch": f"bridge/{ctx.loop_id}",
        }

    seed_file = tmp_path / "seed.md"
    seed_file.write_text(SEED, encoding="utf-8")
    source_repo = tmp_path / "source"
    source_repo.mkdir()
    out = io.StringIO()

    rc = sr.main(
        [
            "--seed-file", str(seed_file),
            "--source-repo", str(source_repo),
            "--work-root", str(tmp_path / "work"),
            "--max-rounds", "1",
            "--round-timeout", "1",
        ],
        run_once_fn=run_once,
        repo_factory=lambda **kw: str(kw["run_root"] / "origin.git"),
        stdout=out,
    )

    assert rc == 0
    assert out.getvalue() == ""
