"""Risk-Level-Policy fuer Bridge-Tasks (Spec 2026-06-12-risk-level-mapping).

Deklarative, enforced Tabelle: kind/adapter -> Risk-Level (read|build|ops).
`ops` existiert als Level, aber KEIN kind/adapter erreicht es — "kein
Admin-Exec ueber die Bridge" ist damit strukturell codiert. Drei Regeln,
fail-closed, kein Override (anders als secret_gate's --allow-secrets):

R1 level-mismatch  Adapter-Capability != Kind-Level (beide Richtungen).
R2 ops-verb        Ops-Verben im AUFTRAGSTEXT (nie im Diff — L12/Gate-vs-Gate:
                   gebaute Diffs prueft weiterhin loop_driver.scan_dangerous).
R3 unknown-field   unbekanntes kind/adapter -> wie ops = Ablehnung. Ein neuer
                   Wert zwingt zur bewussten Policy-Entscheidung hier.

Patterns liegen bewusst im Code (Vorbild loop_driver.DANGEROUS_PATTERNS),
nicht in config.json — ein Security-Gate ist nicht soft-konfigurierbar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LEVELS = ("read", "build", "ops")

KIND_LEVEL = {
    "echo": "read", "review": "read", "research": "read",
    "implement": "build", "test": "build",
}
ADAPTER_CAPABILITY = {
    "echo": "read", "claude": "read", "increment": "read",
    "codex": "build",
}

# Ops-Verben: Scheduled-Task-Verwaltung, Push/Merge in die Base, Admin.
# Treffer im Auftragstext -> Ablehnung. Kleine, dokumentierte FP-Flaeche
# (Spec §R2): Ablehnung ist im Result sichtbar, Umformulieren moeglich.
OPS_PATTERNS = [
    r"\bschtasks\b",
    r"\b(un)?register-scheduledtask\b",
    r"\bgit\s+push\s+\S+\s+(main|master)\b",
    r"\bmerge\b.{0,40}\b(main|master)\b",
    r"\badmin_pin\b",
    r"^/admin\b",
]
_OPS_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in OPS_PATTERNS]


@dataclass(frozen=True)
class Violation:
    rule: str    # "level-mismatch" | "ops-verb" | "unknown-field"
    reason: str  # menschenlesbar, landet im Result/error_text


def check_task(kind: str | None, adapter: str | None,
               body: str | None) -> Violation | None:
    """Prueft einen Task gegen die Policy. None = erlaubt.

    `body` muss der reine AUFTRAGSTEXT sein (Markdown-Body ohne Frontmatter).
    Caller duerfen NICHT das vollstaendige Dokument (Frontmatter + Body)
    uebergeben — Repo-URLs und Branch-Namen im Frontmatter wuerden den R2-Scan
    falsch triggern (FP ohne Override-Ausweg, Spec §Nicht-Ziele).

    Wirft nie — kaputte Eingaben (None/leer/unbekannt) sind R3-Ablehnungen
    (fail-closed), kein Crash im Poller/Writer.
    """
    kind_level = KIND_LEVEL.get(kind or "")
    adapter_cap = ADAPTER_CAPABILITY.get(adapter or "")
    if kind_level is None or adapter_cap is None:
        return Violation(
            rule="unknown-field",
            reason=(f"kind={kind!r} oder adapter={adapter!r} nicht in der "
                    "Policy-Tabelle (risk_policy.py) — fail-closed"))
    if kind_level != adapter_cap:
        return Violation(
            rule="level-mismatch",
            reason=(f"kind={kind} verlangt Level {kind_level}, "
                    f"adapter={adapter} hat Capability {adapter_cap}"))
    for pat, rx in zip(OPS_PATTERNS, _OPS_RE):
        m = rx.search(body or "")
        if m:
            return Violation(
                rule="ops-verb",
                reason=(f"Ops-Verb im Auftrag ({pat}): {m.group(0)!r} — "
                        "Ops laufen nie ueber die Bridge, nur interaktiv"))
    return None
