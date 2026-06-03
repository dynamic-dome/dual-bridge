"""Overnight-Scheduler für dual-bridge.

Arbeitet eine Queue vordefinierter goal-loop-Seeds (docs/overnight/*.md) nachts
SERIELL ab und meldet das Ergebnis am Morgen per Telegram (über bridge_notify).

Design (siehe docs/superpowers/specs/2026-06-03-dual-bridge-overnight-scheduler-design.md):
- read-mostly: schreibt nur den eigenen Sidecar state/_overnight/runs/<UTC>.json.
  Loop-Artefakte (ESCALATION-*.md, Branches) erzeugt loop_driver selbst.
- fail-soft je Seed: ein gescheiterter/eskalierter Seed bricht den Batch NICHT ab.
- fail-closed bei Config: nicht-leere Queue ohne --repo -> Exit 2, nichts gestartet.
- DCO-ready: die gesamte Logik liegt in run_overnight() mit injizierbarer run_fn
  (Default = echter loop_driver-Aufruf im Subprozess). Für DCO wechselt nur der
  Aufrufer, nicht die Kernlogik.

Exit-Mapping (loop_driver-Contract): 0=accepted, 3=escalated, 2/1=error.

Dual-runnable Tests:  python -m pytest scripts/test_bridge_overnight.py
CLI:  python bridge_overnight.py [--dry-run] [--queue DIR] [--repo URL]
                                 [--max-rounds N] [--round-timeout S] [--no-notify]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import bridge_common as bc
import bridge_status as bs
import bridge_notify as bn

OVERNIGHT_DIR_NAME = "_overnight"
RUNS_DIR_NAME = "runs"
DEFAULT_QUEUE = "docs/overnight"
DONE_DIR_NAME = "_done"
SKIP_SUFFIX = ".skip"
# Dateinamen, die nie ein Seed sind, auch wenn sie zufällig einen '## Ziel'-Block
# als Format-Beispiel enthalten (die Queue-README dokumentiert genau dieses Format).
_NON_SEED_NAMES = {"readme.md"}

# loop_driver-Exit-Codes -> Outcome
_EXIT_OUTCOME = {0: "accepted", 3: "escalated", 2: "error", 1: "error"}


# --- Sidecar-State -----------------------------------------------------------
def _runs_dir() -> Path:
    return bs.STATE_DIR / OVERNIGHT_DIR_NAME / RUNS_DIR_NAME


def _write_run_record(record: dict) -> Path:
    """Einen Batch-Run-Record atomar nach state/_overnight/runs/<stamp>.json
    schreiben. Stamp = Start-Zeit (kollisionsarm, sortierbar)."""
    _runs_dir().mkdir(parents=True, exist_ok=True)
    stamp = str(record.get("started", bc.now_iso())).replace(":", "").replace("-", "")
    path = _runs_dir() / f"{stamp}.json"
    bc.write_text_atomic(path, json.dumps(record, ensure_ascii=False, indent=2))
    return path


# --- Queue -------------------------------------------------------------------
def default_queue_dir() -> Path:
    """Die Default-Queue REPO-relativ auflösen (scripts/ -> Repo-Wurzel ->
    docs/overnight), nicht CWD-relativ. Sonst findet ein manueller Aufruf aus
    scripts/ still 0 Seeds, während der registrierte Task (mit -WorkingDirectory
    repoRoot) korrekt liefe — ein leiser, irreführender Fehlschlag."""
    return Path(__file__).resolve().parent.parent / DEFAULT_QUEUE


def _looks_like_seed(path: Path) -> bool:
    """Eine *.md ist nur dann ein Seed, wenn sie (a) NICHT auf der Nicht-Seed-
    Namensliste steht (README dokumentiert das Format inkl. einem '## Ziel'-
    Beispiel und darf NIE selbst als Loop starten) UND (b) einen '## Ziel'-Block
    enthält. So fliegen README/reine Doku raus — sie würden sonst als goal-loop
    gestartet und garantiert eskalieren."""
    if path.name.lower() in _NON_SEED_NAMES:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — unlesbar -> kein Seed
        return False
    # Exakte Heading-Zeile '## Ziel' (nicht startswith — sonst matcht z.B.
    # '## Zielgruppe' fälschlich). Das Heading ist genau das, was loop_driver
    # als Seed-Ziel erwartet.
    return any(line.strip().lower() == "## ziel"
               for line in text.splitlines())


def discover_seeds(queue_dir: Path) -> list[Path]:
    """Seeds der Queue alphabetisch nach Dateiname. Ignoriert:
    - fehlendes/leeres Verzeichnis (-> []),
    - Unterordner (insb. _done/),
    - Dateien mit .skip-Suffix,
    - *.md ohne '## Ziel'-Block (README, reine Doku — kein abnehmbares Ziel).
    Nur *.md-Seeds auf oberster Ebene zählen.
    """
    if not queue_dir.exists() or not queue_dir.is_dir():
        return []
    seeds = [p for p in queue_dir.iterdir()
             if p.is_file()
             and p.suffix == ".md"
             and not p.name.endswith(SKIP_SUFFIX)
             and _looks_like_seed(p)]
    return sorted(seeds, key=lambda p: p.name)


# --- echter Loop-Runner (Default-run_fn) ------------------------------------
def _real_run_fn(*, seed_file: Path, seed_text: str, goal: str, repo: str,
                 max_rounds: int, round_timeout: int) -> dict:
    """Default-Runner: ruft loop_driver.py als Subprozess auf (gehärtetes Env,
    UTF-8-Runtime). Gibt {'exit': rc, ...} zurück. Wirft bei Timeout — der
    Aufrufer wertet das als 'error'."""
    cmd = [
        sys.executable, "-X", "utf8",
        str(Path(__file__).with_name("loop_driver.py")),
        "--mode", "goal-loop",
        "--repo", repo,
        "--base-branch", "main",
        "--max-rounds", str(max_rounds),
        "--round-timeout", str(round_timeout),
        "--seed", seed_text,
    ]
    # Wall-Clock-Cap je Seed: großzügig über die Loop-internen Timeouts hinaus.
    cap = round_timeout * max_rounds + 120
    proc = subprocess.run(
        cmd, cwd=str(Path(__file__).parent),
        env=bc.safe_subprocess_env(),
        capture_output=True, text=True, timeout=cap,
    )
    return {"exit": proc.returncode, "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:]}


# --- Ergebnis-Container ------------------------------------------------------
@dataclass
class BatchResult:
    started: str
    finished: str
    seeds: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def as_record(self) -> dict:
        return {"started": self.started, "finished": self.finished,
                "seeds": self.seeds, "summary": self.summary}


# --- Kernlogik (DCO-ready: reiner Aufruf, austauschbarer run_fn/send_fn) -----
def run_overnight(*, queue_dir: Path, repo: str, max_rounds: int = 4,
                  round_timeout: int = 600, run_fn=None, send_fn=None,
                  dry_run: bool = False, notify: bool = True) -> BatchResult:
    """Die Queue seriell abarbeiten.

    run_fn(seed_file, seed_text, goal, repo, max_rounds, round_timeout) -> dict
        muss {'exit': int, ...} liefern. Default = _real_run_fn (Subprozess).
        Fehler/Timeout aus run_fn werden je Seed als 'error' gewertet (fail-soft).
    send_fn: an bridge_notify.send_overnight_digest weitergereicht (Default Telegram).
    dry_run: plant nur (zählt Seeds), startet KEINE Loops, sendet/schreibt nichts.
    notify: False unterdrückt den Digest-Versand (State wird trotzdem geschrieben).
    """
    run_fn = run_fn or _real_run_fn
    queue_dir = Path(queue_dir)
    seeds = discover_seeds(queue_dir)
    started = bc.now_iso()

    seed_records: list[dict] = []
    summary = {"accepted": 0, "escalated": 0, "error": 0, "total": len(seeds)}

    for seed_file in seeds:
        try:
            seed_text = seed_file.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            seed_text = ""
        goal = _first_goal_line(seed_text)

        if dry_run:
            print(f"[overnight] DRY-RUN würde starten: {seed_file.name} — {goal}")
            seed_records.append({"file": seed_file.name, "goal": goal,
                                 "outcome": "planned", "exit": None})
            continue

        try:
            out = run_fn(seed_file=seed_file, seed_text=seed_text, goal=goal,
                         repo=repo, max_rounds=max_rounds,
                         round_timeout=round_timeout)
            rc = int(out.get("exit", 1))
            outcome = _EXIT_OUTCOME.get(rc, "error")
            rec = {"file": seed_file.name, "goal": goal, "exit": rc,
                   "outcome": outcome, "loop_id": out.get("loop_id"),
                   "rounds": out.get("rounds")}
        except Exception as exc:  # noqa: BLE001  (Timeout, Subprozessfehler, …)
            print(f"[overnight] Seed {seed_file.name} fehlgeschlagen: "
                  f"{type(exc).__name__}: {exc}")
            rec = {"file": seed_file.name, "goal": goal, "exit": None,
                   "outcome": "error", "error": f"{type(exc).__name__}: {exc}"}

        summary[rec["outcome"]] = summary.get(rec["outcome"], 0) + 1
        seed_records.append(rec)

    finished = bc.now_iso()
    result = BatchResult(started=started, finished=finished,
                         seeds=seed_records, summary=summary)

    if dry_run:
        return result  # seiteneffektfrei: kein State, kein Send

    _write_run_record(result.as_record())

    if notify:
        bn.send_overnight_digest(result.as_record(), send_fn=send_fn)

    return result


def _first_goal_line(seed_text: str) -> str:
    """Die erste nicht-leere Zeile unter '## Ziel' als Kurz-Goal (für Logs/Digest).
    Defensiv: leerer String, wenn nicht gefunden."""
    lines = seed_text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## ziel"):
            for nxt in lines[i + 1:]:
                if nxt.strip():
                    return nxt.strip()[:120]
            break
    return ""


# --- CLI ---------------------------------------------------------------------
def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Overnight-Scheduler für dual-bridge (Queue goal-loop-Seeds, read-mostly).")
    p.add_argument("--queue", default=None,
                   help=f"Queue-Verzeichnis mit Seed-*.md (Default: repo-relativ "
                        f"{DEFAULT_QUEUE}).")
    p.add_argument("--repo", default="",
                   help="Repo-URL für alle Seeds (verpflichtend bei nicht-leerer Queue).")
    p.add_argument("--max-rounds", type=int, default=4,
                   help="An loop_driver durchgereicht (Default 4).")
    p.add_argument("--round-timeout", type=int, default=600,
                   help="An loop_driver durchgereicht (Sekunden, Default 600).")
    p.add_argument("--dry-run", action="store_true",
                   help="Nur die Queue + geplante Läufe zeigen; nichts starten/senden/schreiben.")
    p.add_argument("--no-notify", action="store_true",
                   help="Batch läuft, aber KEIN Digest-Versand (nur State).")
    return p.parse_args(argv)


def main(argv=None, *, run_fn=None, send_fn=None) -> int:
    """Exit-Codes: 0=Batch durchgelaufen (auch mit Einzel-Eskalationen),
    2=Fehlkonfiguration (nicht-leere Queue ohne --repo), 1=unerwarteter Abbruch."""
    bc.ensure_utf8_runtime()
    args = _parse_args(argv)
    # Default repo-relativ (CWD-unabhängig); ein explizites --queue gewinnt.
    queue_dir = Path(args.queue) if args.queue else default_queue_dir()
    seeds = discover_seeds(queue_dir)

    # fail-closed: ohne --repo darf bei nicht-leerer Queue NICHTS starten.
    if seeds and not args.repo:
        print("[overnight] --repo fehlt bei nicht-leerer Queue. Abbruch (nichts gestartet).")
        return 2

    try:
        result = run_overnight(
            queue_dir=queue_dir, repo=args.repo, max_rounds=args.max_rounds,
            round_timeout=args.round_timeout, run_fn=run_fn, send_fn=send_fn,
            dry_run=args.dry_run, notify=not args.no_notify)
    except Exception as exc:  # noqa: BLE001
        print(f"[overnight] unerwarteter Abbruch: {type(exc).__name__}: {exc}")
        return 1

    s = result.summary
    print(f"[overnight] fertig: {s.get('total', 0)} Seeds — "
          f"{s.get('accepted', 0)} accepted, {s.get('escalated', 0)} eskaliert, "
          f"{s.get('error', 0)} Fehler.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main(sys.argv[1:]))
