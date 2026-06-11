"""Secrets pre-send gate for outgoing bridge tasks (Erw. 1.4 / DCO todo #7877).

Scans a task document BEFORE it is written into the lane outbox so that
credentials can never reach the Drive sharepoint (Manifest rule: no secrets in
tasks). Two detector families, mirroring the gitleaks / detect-secrets
approach, stdlib-only:

1. Format detectors — regexes for well-known token shapes (Telegram bot token,
   GitHub PATs, model-provider ``sk-`` keys, AWS access-key ids, PEM private
   key blocks).
2. Entropy detector — Shannon entropy over long url-safe/base64-ish tokens
   (>= 20 chars, >= 4.5 bits/char). Hex-only tokens are deliberately EXEMPT:
   bridge tasks routinely carry commit hashes and sha256 proofs, which would
   otherwise false-positive on every other task (deviation from the seed's
   "hex >= 3.0" — documented trade-off, format detectors stay armed for the
   real hex-shaped credentials we know).

Findings carry a REDACTED excerpt only — the gate must never echo the secret
it just caught.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Well-known token formats. All patterns target the SHAPE of real credentials;
# a bare provider prefix in prose ("beginnt mit sk-") does not match.
_FORMAT_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("telegram-bot-token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("model-api-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# Candidate tokens for the entropy check: long runs of base64/url-safe chars.
_TOKEN_RE = re.compile(r"[A-Za-z0-9+/=_-]{20,}")
_HEX_RE = re.compile(r"[0-9a-fA-F]+\Z")
_DIGITS_DASH_RE = re.compile(r"[0-9-]+\Z")

ENTROPY_THRESHOLD = 4.5
MIN_TOKEN_LEN = 20
_EXCERPT_KEEP = 6


@dataclass(frozen=True)
class Finding:
    kind: str
    excerpt: str  # redacted — first few chars only


def _shannon_bits_per_char(token: str) -> float:
    counts = Counter(token)
    n = len(token)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _redact(match_text: str) -> str:
    return f"{match_text[:_EXCERPT_KEEP]}…[redacted]"


def scan_text(text: str) -> list[Finding]:
    """Return all secret findings in `text` (empty list = clean)."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for kind, rx in _FORMAT_PATTERNS:
        for m in rx.finditer(text):
            key = (kind, m.group(0))
            if key not in seen:
                seen.add(key)
                findings.append(Finding(kind=kind, excerpt=_redact(m.group(0))))

    flagged = {m for (_k, m) in seen}
    for m in _TOKEN_RE.finditer(text):
        token = m.group(0)
        if token in flagged or len(token) < MIN_TOKEN_LEN:
            continue
        # hex-only -> commit hash / sha256 proof, digits-and-dashes -> task id.
        if _HEX_RE.match(token) or _DIGITS_DASH_RE.match(token):
            continue
        if _shannon_bits_per_char(token) >= ENTROPY_THRESHOLD:
            key = ("high-entropy-token", token)
            if key not in seen:
                seen.add(key)
                findings.append(
                    Finding(kind="high-entropy-token", excerpt=_redact(token)))

    return findings
