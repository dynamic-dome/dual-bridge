"""Stage 0 — Latency probe: measure real A->B->A roundtrip time.

Run this on Laptop A *while* `handoff_poll.py --watch` runs on Laptop B.

It writes N echo tasks (one at a time), waits for each matching result to
appear in the inbox, and records the wall-clock roundtrip. At the end it prints
a small stats summary and appends a line to latency-baseline.md for the record.

Usage:
    python latency_probe.py                 # 5 probes, 1s apart
    python latency_probe.py --count 10
    python latency_probe.py --count 5 --gap 3 --timeout 180

The roundtrip measured here is end-to-end as the *user* experiences it:
  task written (A)  ->  Drive sync up  ->  B polls + claims + echoes
                    ->  Drive sync down ->  result visible to A
So it includes B's poll interval (default 15s). To isolate pure sync latency,
run B's poller with a short interval (e.g. --interval 2) during the probe.
"""
from __future__ import annotations

import argparse
import sys
import time

import bridge_common as bc


def _write_probe(index: int) -> tuple[str, float]:
    """Write one probe task. Returns (task_id, monotonic_start)."""
    task_id = bc.make_task_id()
    frontmatter = {
        "created": bc.now_iso(),
        "agent": f"laptop-a-claude@{bc.DEVICE}",
        "target_agent": "laptop-b-worker",
        "purpose": "handoff",
        "status": "open",
        "task_id": task_id,
        "kind": "echo",
        "claimed_by": "",
        "claimed_at": "",
        "probe": f"latency-{index}",
    }
    body = (
        "## Auftrag\n"
        f"Latenz-Probe #{index} — bitte echo (kein LLM).\n\n"
        "## Akzeptanzkriterien\n"
        "- [ ] Result im inbox/ mit demselben task_id\n\n"
        "## Ergebnis\n"
        "<B füllt das>\n"
    )
    out_path = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(out_path, bc.build_document(frontmatter, body))
    # time.monotonic() is allowed; only Date.now()/random-style wall clock for
    # *ids* must stay deterministic. Wall-clock measurement is the whole point.
    return task_id, time.monotonic()


def _wait_for_result(task_id: str, timeout: float) -> float | None:
    """Poll the inbox for result-<task_id>.md. Returns monotonic finish time
    or None on timeout."""
    target = bc.inbox_dir() / f"result-{task_id}.md"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if target.exists():
            return time.monotonic()
        time.sleep(0.5)
    return None


def _archive_result(task_id: str) -> None:
    """Move the collected result into _processed/ (no delete)."""
    src = bc.inbox_dir() / f"result-{task_id}.md"
    if src.exists():
        try:
            src.replace(bc.processed_dir() / src.name)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure A->B->A roundtrip latency.")
    parser.add_argument("--count", type=int, default=5, help="Number of probes.")
    parser.add_argument("--gap", type=float, default=1.0, help="Seconds between probes.")
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="Per-probe wait timeout (s)."
    )
    args = parser.parse_args(argv)

    bc.ensure_dirs()
    print(f"[probe] Bridge-Root: {bc.bridge_root()}")
    print(f"[probe] {args.count} Proben, Timeout {args.timeout:.0f}s je Probe.")
    print("[probe] Voraussetzung: auf Laptop B läuft `handoff_poll.py --watch`.\n")

    samples: list[float] = []
    timeouts = 0

    for i in range(1, args.count + 1):
        task_id, start = _write_probe(i)
        print(f"[probe] #{i} gesendet (task_id {task_id}) — warte auf Result …", flush=True)
        finish = _wait_for_result(task_id, args.timeout)
        if finish is None:
            print(f"[probe] #{i} TIMEOUT nach {args.timeout:.0f}s — kein Result.")
            timeouts += 1
        else:
            rt = finish - start
            samples.append(rt)
            print(f"[probe] #{i} OK — Roundtrip {rt:.1f}s")
            _archive_result(task_id)
        if i < args.count:
            time.sleep(args.gap)

    print("\n" + "=" * 50)
    print(f"[probe] Fertig: {len(samples)}/{args.count} erfolgreich, {timeouts} Timeout(s).")
    if samples:
        samples_sorted = sorted(samples)
        n = len(samples_sorted)
        mn = samples_sorted[0]
        mx = samples_sorted[-1]
        avg = sum(samples_sorted) / n
        med = samples_sorted[n // 2]
        print(f"[probe] min {mn:.1f}s | median {med:.1f}s | avg {avg:.1f}s | max {mx:.1f}s")
        _append_baseline(samples_sorted, timeouts, args)
    else:
        print("[probe] Keine erfolgreichen Proben — läuft der Poller auf Laptop B?")
    print("=" * 50)
    return 0


def _append_baseline(samples: list[float], timeouts: int, args) -> None:
    """Append a one-line record to latency-baseline.md (local, not Sharepoint)."""
    doc_dir = bc.Path(__file__).resolve().parent.parent / "docs"
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / "latency-baseline.md"
    n = len(samples)
    avg = sum(samples) / n
    line = (
        f"- {bc.now_iso()} | {bc.DEVICE} | n={n} ok, {timeouts} timeout | "
        f"min {samples[0]:.1f}s · median {samples[n//2]:.1f}s · avg {avg:.1f}s · "
        f"max {samples[-1]:.1f}s | poll-gap unbekannt (B-seitig)\n"
    )
    header = "# Dual-Bridge Latenz-Baseline\n\n_Append-only. Eine Zeile pro Probe-Lauf._\n\n"
    if not path.exists():
        bc.write_text_utf8(path, header)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
    print(f"[probe] Baseline-Zeile angehängt → {path}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
