"""Documentation contract for the reusable Superpowers skill export."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "docs" / "superpowers" / "skills" / "dual-bridge-two-model-review" / "SKILL.md"


def test_two_model_review_skill_export_exists_and_names_triggers():
    text = SKILL.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "name: dual-bridge-two-model-review" in text
    assert "description: Use when" in text
    assert "verifier" in text.lower()
    assert "builder" in text.lower()
    assert "two-model" in text.lower()
    assert "codex" in text.lower()
    assert "claude" in text.lower()


def test_two_model_review_skill_exports_operational_pattern():
    text = SKILL.read_text(encoding="utf-8")

    required = [
        "python -X utf8 -m pytest -q",
        "python -X utf8 loop_driver.py --mode goal-loop",
        "python -X utf8 loop_driver.py --mode relay-loop",
        "codex",
        "claude-build",
        "claude",
        "codex-review",
        "VERDICT: accepted",
        "VERDICT: rejected",
        "VERDICT: escalate",
        "docs/CHANGELOG.md",
        "docs/CAPABILITIES.md",
    ]
    for marker in required:
        assert marker in text


def test_docs_dod_mentions_skill_export_in_canonical_docs():
    changelog = (ROOT / "docs" / "CHANGELOG.md").read_text(encoding="utf-8")
    capabilities = (ROOT / "docs" / "CAPABILITIES.md").read_text(encoding="utf-8")

    assert "dual-bridge-two-model-review" in changelog
    assert "dual-bridge-two-model-review" in capabilities
    assert "docs/superpowers/skills/dual-bridge-two-model-review/SKILL.md" in capabilities
