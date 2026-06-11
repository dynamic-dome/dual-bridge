"""Pre-send secret scanner for outgoing bridge tasks.

Pure stdlib and intentionally conservative: known secret formats are blocked
directly; entropy findings are only reported for token-like runs.
"""
from __future__ import annotations

import math
import re

Finding = dict[str, object]

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b")),
    ("github_token", re.compile(r"\b(?:ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("openai_or_anthropic_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("pem_private_key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
)

_HEX_RE = re.compile(r"\b[0-9a-fA-F]{20,}\b")
_BASE64_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{20,}\b")
_BASE64_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=_-")


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    total = len(value)
    counts = {char: value.count(char) for char in set(value)}
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _redact(value: str) -> str:
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def _line_col(text: str, start: int) -> tuple[int, int]:
    line = text.count("\n", 0, start) + 1
    last_break = text.rfind("\n", 0, start)
    col = start + 1 if last_break < 0 else start - last_break
    return line, col


def _is_probable_commit_context(text: str, start: int) -> bool:
    prefix = text[max(0, start - 24):start].lower()
    return any(marker in prefix for marker in ("commit ", "sha ", "sha1 ", "revision "))


def _finding(kind: str, text: str, match: re.Match[str]) -> Finding:
    line, col = _line_col(text, match.start())
    value = match.group(0)
    return {
        "kind": kind,
        "line": line,
        "col": col,
        "redacted": _redact(value),
        "length": len(value),
    }


def scan_text(text: str) -> list[Finding]:
    """Return secret findings in ``text``.

    Findings are dictionaries with ``kind``, location, redacted match text, and
    match length. Raw secret values are never returned.
    """
    findings: list[Finding] = []
    occupied: list[tuple[int, int]] = []

    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            findings.append(_finding(kind, text, match))
            occupied.append(match.span())

    def overlaps_known(match: re.Match[str]) -> bool:
        start, end = match.span()
        return any(start < known_end and end > known_start for known_start, known_end in occupied)

    for match in _HEX_RE.finditer(text):
        if overlaps_known(match) or _is_probable_commit_context(text, match.start()):
            continue
        if _entropy(match.group(0)) >= 3.0:
            findings.append(_finding("high_entropy_hex", text, match))

    for match in _BASE64_RE.finditer(text):
        value = match.group(0)
        if overlaps_known(match) or set(value) - _BASE64_CHARS:
            continue
        if re.fullmatch(r"[0-9a-fA-F]+", value):
            continue
        if _entropy(value.rstrip("=")) >= 4.5:
            findings.append(_finding("high_entropy_base64", text, match))

    return findings
