"""Regression tests for the F1/F2/F4 hardening fixes.

Runs against an isolated temp bridge root (DUAL_BRIDGE_ROOT) — never touches
the real Sharepoint. Pure stdlib + assert, no pytest needed:
    python test_hardening.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-test-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    return root


def test_f2_unique_ids() -> None:
    """F2: many ids created in a tight loop must all be unique."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    ids = [bc.make_task_id() for _ in range(5000)]
    assert len(set(ids)) == len(ids), f"ID-Kollision: {len(ids) - len(set(ids))} Duplikate"
    print(f"  F2 OK — 5000 IDs, 0 Kollisionen (Beispiel: {ids[0]})")


def test_f2_exclusive_write() -> None:
    """F2/F1: exclusive write refuses to overwrite an existing file."""
    import bridge_common as bc
    bc.ensure_dirs()
    p = bc.outbox_dir() / "excl-test.md"
    assert bc.write_text_exclusive(p, "first") is True
    assert bc.write_text_exclusive(p, "second") is False, "Overwrite hätte verhindert werden müssen"
    assert p.read_text(encoding="utf-8") == "first", "Inhalt wurde überschrieben!"
    print("  F2 OK — write_text_exclusive verhindert stilles Überschreiben")


def test_f3_atomic_write() -> None:
    """F3: atomic write leaves no temp file behind and writes full content."""
    import bridge_common as bc
    bc.ensure_dirs()
    p = bc.outbox_dir() / "atomic-test.md"
    bc.write_text_atomic(p, "voller Inhalt mit Ümlaut")
    assert p.read_text(encoding="utf-8-sig") == "voller Inhalt mit Ümlaut"
    leftover = list(bc.outbox_dir().glob(".tmp-*"))
    assert not leftover, f"Temp-Datei nicht aufgeräumt: {leftover}"
    print("  F3 OK — atomic write, kein Temp-Rest, Umlaut erhalten")


def test_f4_stranded_claim_gets_archived() -> None:
    """F4: a .claimed-* task left in outbox (move had failed) is re-archived
    on the next poll_once, and is NOT re-processed."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    # Simulate a stranded done-but-not-moved claimed task.
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "done", "task_id": task_id,
        "kind": "echo", "claimed_by": "laptop-b-worker@TESTDEV", "claimed_at": bc.now_iso(),
    }
    stranded = bc.outbox_dir() / f"task-{task_id}.claimed-TESTDEV-abcd1234.md"
    bc.write_text_utf8(stranded, bc.build_document(fm, "## Auftrag\nx\n"))
    # Its result already exists (it was written before the move failed).
    bc.write_text_utf8(bc.inbox_dir() / f"result-{task_id}.md", "done earlier")

    n = hp.poll_once()
    assert n == 0, "Stranded-Task darf NICHT als neu verarbeitet zählen"
    assert not stranded.exists(), "Stranded-Task wurde nicht aus outbox archiviert"
    assert (bc.processed_dir() / stranded.name).exists(), "Stranded-Task nicht in _processed"
    print("  F4 OK — liegengebliebener .claimed-Task nachgeholt archiviert, nicht reprozessiert")


def test_f1_double_claim_one_result() -> None:
    """F1: if a result already exists, process_one bails (exclusive) and the
    task is archived rather than producing a duplicate result."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "echo", "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nhallo\n"))
    # Pretend another worker already produced the result.
    pre_existing = bc.inbox_dir() / f"result-{task_id}.md"
    bc.write_text_utf8(pre_existing, "result vom anderen worker")

    produced = hp.process_one(task)
    assert produced is False, "process_one hätte bei existierendem Result bailen müssen"
    assert pre_existing.read_text(encoding="utf-8-sig") == "result vom anderen worker", \
        "Bestehendes Result wurde überschrieben!"
    # task should be archived, not stuck in outbox
    assert not list(bc.outbox_dir().glob(f"task-{task_id}*")), "Task blieb in outbox stecken"
    print("  F1 OK — Doppel-Claim: kein Result-Overwrite, Task archiviert statt stuck")


def main() -> int:
    _fresh_bridge()
    print("=== Härtungs-Regressionstests (F1/F2/F3/F4) ===")
    tests = [
        test_f2_unique_ids,
        test_f2_exclusive_write,
        test_f3_atomic_write,
        test_f4_stranded_claim_gets_archived,
        test_f1_double_claim_one_result,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
    print("=" * 48)
    if failed:
        print(f"FEHLER: {failed}/{len(tests)} Tests fehlgeschlagen.")
        return 1
    print(f"Alle {len(tests)} Tests bestanden.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
