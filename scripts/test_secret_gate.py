"""Tests for the secrets pre-send gate (Erw. 1.4 / DCO todo #7877).

All positive fixtures are FAKE tokens in the correct FORMAT — never real
credentials. Negative tests pin the false-positive surface that bridge tasks
hit daily (URLs, commit hashes, task ids, plain prose).
"""
from __future__ import annotations

import bridge_common as bc
import handoff_write
import secret_gate


# --- format detectors --------------------------------------------------------


def _kinds(text):
    return [f.kind for f in secret_gate.scan_text(text)]


def test_telegram_bot_token_detected():
    text = "hier TELEGRAM_TOKEN=123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCr4KpM77x"
    assert "telegram-bot-token" in _kinds(text)


def test_github_classic_pat_detected():
    text = "auth via ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345 im env"
    assert "github-token" in _kinds(text)


def test_github_fine_grained_pat_detected():
    text = "github_pat_11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz0123456789"
    assert "github-fine-grained-pat" in _kinds(text)


def test_model_api_key_detected():
    text = "der key ist sk-ant-api03-AbCdEf_GhIjKlMnOpQ123 bitte nutzen"
    assert "model-api-key" in _kinds(text)


def test_aws_access_key_id_detected():
    text = "credentials: AKIAIOSFODNN7EXAMPLE / weiter im Text"
    assert "aws-access-key-id" in _kinds(text)


def test_private_key_block_detected():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    assert "private-key-block" in _kinds(text)


# --- entropy detector --------------------------------------------------------


def test_high_entropy_base64ish_token_detected():
    # 43 chars, mixed case + digits + url-safe symbols -> entropy well above 4.5
    text = "wert: xK9pQ2vR8mN4jL7wT3yU6iO1aS5dF0gHbZcVeXnJ_M-"
    assert "high-entropy-token" in _kinds(text)


def test_low_entropy_long_token_not_flagged():
    assert _kinds("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") == []


# --- false-positive surface (bridge-task daily business) ---------------------


def test_plain_prose_clean():
    assert _kinds("Baue ein README fuer das Tools-Lab und teste alles.") == []


def test_repo_url_clean():
    assert _kinds("repo=https://github.com/dynamic-dome/dual-bridge kind=implement") == []


def test_full_sha1_commit_hash_clean():
    # hex-only tokens are treated as hashes (commits / sha256 proofs), not secrets
    assert _kinds("gemergt als 38a1b7ac9d2e4f6081b3c5d7e9f0a1b2c3d4e5f6 auf main") == []


def test_sha256_hash_clean():
    h = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert _kinds(f"checksum {h} ok") == []


def test_task_id_clean():
    assert _kinds("task_id: 20260611-110951-760678-0-fc78 round 2") == []


def test_bare_sk_prefix_clean():
    assert _kinds("OpenAI-Keys beginnen mit sk- (Prefix erwaehnt, kein Token)") == []


# --- redaction ----------------------------------------------------------------


def test_excerpt_is_redacted():
    text = "TELEGRAM_TOKEN=123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCr4KpM77x"
    findings = secret_gate.scan_text(text)
    assert findings, "fixture must trigger"
    for f in findings:
        assert "AAEhBOweik6ad9r_QXMENQjcrGbqCr4KpM77x" not in f.excerpt
        assert f.excerpt.endswith("[redacted]")


# --- handoff_write integration ------------------------------------------------


def _outbox_tasks():
    return list(bc.lane_outbox(bc.send_lane()).glob("task-*.md"))


def test_handoff_write_blocks_secret_task(capsys):
    rc = handoff_write.main(
        ["nutze ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345 zum klonen"])
    assert rc == 2
    assert _outbox_tasks() == []
    err = capsys.readouterr().err
    assert "secret-gate" in err
    assert "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345" not in err  # redacted


def test_handoff_write_allow_secrets_overrides():
    rc = handoff_write.main(
        ["--allow-secrets",
         "nutze ghp_AbCdEfGhIjKlMnOpQrStUvWxYz012345 zum klonen"])
    assert rc == 0
    assert len(_outbox_tasks()) == 1


def test_handoff_write_clean_task_unaffected():
    rc = handoff_write.main(["ganz normaler Auftrag ohne Geheimnisse"])
    assert rc == 0
    assert len(_outbox_tasks()) == 1
