"""Phase-0 gate-vorstufe tests. Pure stdlib + assert, no pytest:
    python test_gate_evidence.py

Covers two features:
  - GT1 (Task A): generic mirroring of gate-evidence fields (gate_id/run_id/
    stage) from a task's frontmatter into the result's frontmatter. Mirrored
    only when present and non-empty — absent fields must NOT appear.
  - Stage-2b core (Task B): kind:review verdict semantics. An explicit
    `VERDICT: accepted` yields accepted; everything else (missing/ambiguous/
    unknown token) is fail-closed to rejected. Non-review kinds carry no verdict.

Isolated via DUAL_BRIDGE_ROOT -> tmp dir; DUAL_BRIDGE_ENDPOINT sets identity.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-gate-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_mirrors_gate_fields_into_result_fm() -> None:
    _fresh_bridge("claude@laptop-a")  # A receives on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "gate_id": "gate-x", "run_id": "run-y", "stage": "build",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nspiegel\n"))
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert rfm.get("gate_id") == "gate-x", f"gate_id not mirrored: {rfm.get('gate_id')!r}"
    assert rfm.get("run_id") == "run-y", f"run_id not mirrored: {rfm.get('run_id')!r}"
    assert rfm.get("stage") == "build", f"stage not mirrored: {rfm.get('stage')!r}"
    print("  gate OK — gate_id/run_id/stage mirrored from task FM into result FM")


def test_absent_gate_fields_not_in_result_fm() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nspiegel\n"))
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert "gate_id" not in rfm, f"gate_id must not be smuggled in: {rfm.get('gate_id')!r}"
    assert "run_id" not in rfm, f"run_id must not be smuggled in: {rfm.get('run_id')!r}"
    assert "stage" not in rfm, f"stage must not be smuggled in: {rfm.get('stage')!r}"
    print("  gate OK — absent gate fields are NOT added to result FM")


def _run_review_with_fake_claude(fake_answer: str, *, kind: str = "review"):
    """Register a fake `claude` runner that returns a controlled RunnerResult,
    then run one review task (no repo) through process_one and return the
    parsed result frontmatter. Verdict extraction is exercised end-to-end."""
    _fresh_bridge("claude@laptop-a")  # A receives on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()

    def fake_claude(auftrag, fm, workroot, **kw):
        return runners.RunnerResult(status="done", antwort=fake_answer)

    runners.register_runner("claude", fake_claude)

    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": kind, "adapter": "claude",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nreview this\n"))
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    return rfm, rbody


def test_review_verdict_accepted() -> None:
    rfm, _ = _run_review_with_fake_claude(
        "Looks correct, tests pass.\nVERDICT: accepted")
    assert rfm.get("verdict") == "accepted", f"verdict not accepted: {rfm.get('verdict')!r}"
    print("  review OK — VERDICT: accepted -> verdict == accepted")


def test_review_verdict_rejected() -> None:
    rfm, _ = _run_review_with_fake_claude(
        "Found a bug in the loop.\nVERDICT: rejected")
    assert rfm.get("verdict") == "rejected", f"verdict not rejected: {rfm.get('verdict')!r}"
    print("  review OK — VERDICT: rejected -> verdict == rejected")


def test_review_fail_closed_no_marker() -> None:
    """Fail-closed PFLICHT: a reviewer answer WITHOUT a VERDICT marker must
    yield verdict:rejected — never accepted, never missing."""
    rfm, _ = _run_review_with_fake_claude(
        "I am not sure, the diff is large and I ran out of context.")
    assert rfm.get("verdict") == "rejected", \
        f"fail-closed violated: missing marker must be rejected, got {rfm.get('verdict')!r}"
    print("  review OK — no VERDICT marker -> fail-closed rejected")


def test_non_review_has_no_verdict() -> None:
    """A non-review task (kind=research) must NOT get a verdict field, even if
    its answer happens to contain a VERDICT line — verdict is review-only."""
    rfm, _ = _run_review_with_fake_claude(
        "Some research output.\nVERDICT: accepted", kind="research")
    assert "verdict" not in rfm, f"verdict must be review-only, leaked: {rfm.get('verdict')!r}"
    print("  review OK — non-review task carries NO verdict field")


def main() -> int:
    print("=== Phase-0 Gate-Vorstufe-Tests (GT1 mirroring + Stage-2b verdict) ===")
    tests = [
        test_mirrors_gate_fields_into_result_fm,
        test_absent_gate_fields_not_in_result_fm,
        test_review_verdict_accepted,
        test_review_verdict_rejected,
        test_review_fail_closed_no_marker,
        test_non_review_has_no_verdict,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    print("=" * 60)
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
