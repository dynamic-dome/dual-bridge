from __future__ import annotations

import importlib

import bridge_common as bc


def test_scan_text_detects_common_fake_secret_formats() -> None:
    import secret_gate

    text = "\n".join(
        [
            "telegram=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcd_1234",
            "github=ghp_abcdefghijklmnopqrstuvwxyzABCDEF123456",
            "github_pat=github_pat_11AAAAAAA0123456789abcdefABCDEF0123456789abcdefABCDEF",
            "openai=sk-testabcdefghijklmnopqrstuvwxyz1234567890ABCD",
            "anthropic=sk-ant-testabcdefghijklmnopqrstuvwxyz1234567890ABCD",
            "aws=AKIAIOSFODNN7EXAMPLE",
            "-----BEGIN PRIVATE KEY-----",
        ]
    )

    findings = secret_gate.scan_text(text)
    kinds = {finding["kind"] for finding in findings}

    assert "telegram_bot_token" in kinds
    assert "github_token" in kinds
    assert "openai_or_anthropic_key" in kinds
    assert "aws_access_key_id" in kinds
    assert "pem_private_key" in kinds
    assert all("redacted" in finding for finding in findings)


def test_scan_text_detects_high_entropy_base64_and_hex_tokens() -> None:
    import secret_gate

    text = (
        "payload token zYxWvUtSrQpOnMlKjIhGfEdCbA9876543210+/zz "
        "and hex 0123456789abcdef0123456789abcdef01234567"
    )

    kinds = {finding["kind"] for finding in secret_gate.scan_text(text)}

    assert "high_entropy_base64" in kinds
    assert "high_entropy_hex" in kinds


def test_scan_text_ignores_urls_commit_hashes_and_normal_prose() -> None:
    import secret_gate

    text = "\n".join(
        [
            "Bitte pruefe https://github.com/dynamic-dome/dual-bridge/issues/123.",
            "Commit abcdef0123456789abcdef0123456789abcdef01 ist nur ein SHA.",
            "Normale Prosa mit langen Woertern wie Implementierungsbeschreibung.",
            "Pfad C:/Users/domes/AI/dual-bridge/scripts/handoff_write.py",
        ]
    )

    assert secret_gate.scan_text(text) == []


def test_handoff_write_blocks_secret_before_writing(capsys) -> None:
    import handoff_write as hw

    importlib.reload(hw)
    rc = hw.main(["deploy with token ghp_abcdefghijklmnopqrstuvwxyzABCDEF123456"])

    assert rc == 2
    assert list(bc.outbox_dir().glob("task-*.md")) == []
    captured = capsys.readouterr()
    assert "Secrets-Gate" in captured.err
    assert "ghp_" in captured.err
    assert "ABCDEF123456" not in captured.err


def test_handoff_write_allow_secrets_bypasses_gate() -> None:
    import handoff_write as hw

    importlib.reload(hw)
    rc = hw.main(
        [
            "--allow-secrets",
            "deliberate fake token ghp_abcdefghijklmnopqrstuvwxyzABCDEF123456",
        ]
    )

    assert rc == 0
    assert len(list(bc.outbox_dir().glob("task-*.md"))) == 1
