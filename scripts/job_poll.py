"""HTTP-Worker-Poll-Loop für den DCO-Job-Pull (Laptop B).

Der fehlende Daemon, der den DCO-Job-Pull tatsächlich anschmeißt. Die DCO-Seite
(jobs.claim_next / requeue_stale / HTTP-Endpunkte) und der Transport-Baustein
(bridge_transport.HttpSource) sind fertig — hier kommt der Loop, der sie nutzt:

    source = get_source()                 # DUAL_BRIDGE_TRANSPORT=http
    while ...:
        item = source.claim_next()        # GET /jobs/next   (204 = leer)
        if item is None: backoff; continue
        rc = process_item(item, run_fn)   # loop_driver --mode goal-loop -> rc
        source.publish_result(item, rc)   # POST /jobs/<id>/result

Run-Pfad: derselbe wie der Overnight-Scheduler — loop_driver.py --mode goal-loop
als Subprozess (bridge_overnight._real_run_fn-Muster), damit der rc-Vertrag
(0=accepted, 3=escalated, 2=config/resume-error, 1=other) erprobt und identisch
zur DCO-Seite (_EXIT_MAP) bleibt. KEINE Status-Erzwingung: publish_result schickt
result_status=None — der DCO mappt rc auf den finalen Status (Single Source of
Truth). result_payload (gekürztes stdout/stderr) ist rein informativ.

Env (gelesen von bridge_transport.get_source()):
    DUAL_BRIDGE_TRANSPORT   = http              (Pflicht für diesen Worker)
    DCO_BRIDGE_URL          = http://host:port/api   (MUSS auf /api enden)
    DCO_BRIDGE_TOKEN        = <BRIDGE_API_TOKEN des DCO>
    DUAL_BRIDGE_WORKER_TYPE = dual-bridge        (Default)

CLI: --once | --watch [--interval N] [--repo URL] [--max-rounds N] [--round-timeout S]
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import bridge_common as bc


# --- Eingabe-Parser ----------------------------------------------------------

@dataclass
class ParsedJob:
    """Geparster input_text eines Bridge-Jobs.

    Spiegelt den DCO-Parser bridge_router.parse_seed_line, mit GENAU EINER
    bewussten Abweichung: fehlendes repo= wirft NICHT, sondern liefert repo=None.
    Die Fehler-Policy (rc 2 bei repo is None) lebt in process_item, nicht hier —
    so bleibt der Parser total (ein kaputter Job kann den Loop nie killen)."""
    repo: str | None
    kind: str
    adapter: str
    seed: str


def parse_input_text(text: str) -> ParsedJob:
    """Zerlege den rohen Todo-/Job-Text in (repo, kind, adapter, seed).

    Erste Zeile: split()-getrennte key=value-Direktiven (Tokens ohne = werden
    ignoriert). Rest: das Ziel/Briefing (seed). Defaults wie im DCO: kind=implement,
    adapter=codex. Wirft NIE — fehlt/leer repo= -> repo=None, leerer Text -> seed="".
    """
    lines = text.strip().splitlines()
    if not lines:
        return ParsedJob(repo=None, kind="implement", adapter="codex", seed="")

    directives: dict[str, str] = {}
    for token in lines[0].strip().split():
        if "=" in token:
            key, _, value = token.partition("=")
            directives[key.strip()] = value.strip()

    repo = directives.get("repo") or None
    seed = "\n".join(lines[1:]).strip()
    return ParsedJob(
        repo=repo,
        kind=directives.get("kind", "implement"),
        adapter=directives.get("adapter", "codex"),
        seed=seed,
    )


# --- Seed-Strukturierung (loop_driver verlangt ## Ziel + ## Done-Kriterien) ---

def ensure_seed_structure(seed: str) -> str:
    """Bringe einen rohen Seed ins goal-loop-Format, falls noch nicht geschehen.

    loop_driver.parse_seed verlangt einen '## Ziel'-Block UND mindestens einen
    '- '-Listenpunkt unter '## Done-Kriterien' — sonst rc 2 ('seed has no ...').
    Der DCO-Job-Text ist aber freier Fließtext. Dieser Wrapper macht ihn lauffähig:

    - Enthält der Seed beide Blöcke schon -> unverändert durchreichen (bewusst
      strukturierter Seed).
    - Sonst: alle 'Done:'/'Done-Kriterium:'-Zeilen werden Done-Kriterien, der Rest
      wird das Ziel. Fehlt ein Done-Kriterium ganz, ein generisches Fallback, damit
      parse_seed nicht an leeren Kriterien scheitert.
    """
    low = seed.lower()
    if "## ziel" in low and "## done-kriterien" in low:
        return seed

    goal_lines: list[str] = []
    criteria: list[str] = []
    for raw in seed.splitlines():
        line = raw.strip()
        if not line:
            continue
        low_line = line.lower()
        if low_line.startswith("done:") or low_line.startswith("done-kriterium:") \
                or low_line.startswith("done-kriterien:"):
            crit = line.split(":", 1)[1].strip()
            if crit:
                criteria.append(crit)
        else:
            goal_lines.append(line)

    goal = " ".join(goal_lines).strip() or "Arbeite den Auftrag ab."
    if not criteria:
        criteria = ["Der Auftrag ist vollständig umgesetzt und die Tests sind grün."]

    crit_block = "\n".join(f"- {c}" for c in criteria)
    return f"## Ziel\n{goal}\n\n## Done-Kriterien\n{crit_block}\n"


# --- Run-Pfad (Default: loop_driver --mode goal-loop, wie bridge_overnight) ---

def _real_run_fn(*, repo: str, seed: str, adapter: str,
                 max_rounds: int, round_timeout: int) -> dict:
    """Default-Runner: ruft loop_driver.py --mode goal-loop als Subprozess auf
    (gehärtetes Env, UTF-8-Runtime). Gibt {'exit': rc, ...} zurück. Wirft bei
    Timeout — der Aufrufer (process_item) wertet das als rc 1 (fail-soft).

    Spiegelt bridge_overnight._real_run_fn (gleiches cmd, gleicher Wall-Clock-Cap,
    gleicher {'exit': ...}-Vertrag), getriggert durch einen geclaimten HTTP-Job
    statt durch eine Seed-Queue. adapter wird an loop_driver durchgereicht."""
    cmd = [
        sys.executable, "-X", "utf8",
        str(Path(__file__).with_name("loop_driver.py")),
        "--mode", "goal-loop",
        "--repo", repo,
        "--base-branch", "main",
        "--adapter", adapter,
        "--max-rounds", str(max_rounds),
        "--round-timeout", str(round_timeout),
        "--seed", seed,
    ]
    cap = round_timeout * max_rounds + 120
    proc = subprocess.run(
        cmd, cwd=str(Path(__file__).parent),
        env=bc.safe_subprocess_env(),
        capture_output=True, text=True, timeout=cap,
    )
    return {"exit": proc.returncode, "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-2000:]}


def process_item(item, run_fn=None, *, max_rounds: int = 4,
                 round_timeout: int = 600, out_payload: dict | None = None) -> int:
    """Arbeite einen geclaimten WorkItem ab und liefere den rc.

    parst item.input_text -> (repo, seed, adapter). Fehlt repo -> rc 2 (Config-
    Fehler), ohne run_fn aufzurufen. Sonst run_fn(...) -> {'exit': rc}; ein Crash/
    Timeout aus run_fn wird zu rc 1 gekapselt (fail-soft, damit ein kaputter Job
    den Loop nie killt). Der DCO mappt rc selbst auf den finalen Status.

    out_payload (optional, in-place gefüllt): bekommt den run_fn-Output bzw. eine
    Fehlerbeschreibung, damit die Ursache NICHT verloren geht (Live-Bug 2026-06-04:
    ein fehlgeschlagener Job zeigte im DCO nur 'error' ohne stdout/stderr)."""
    run_fn = run_fn or _real_run_fn
    parsed = parse_input_text(item.input_text)
    if parsed.repo is None:
        if out_payload is not None:
            out_payload["error"] = "config: seed ohne repo= (rc 2)"
        return 2
    try:
        seed = ensure_seed_structure(parsed.seed)
        out = run_fn(repo=parsed.repo, seed=seed, adapter=parsed.adapter,
                     max_rounds=max_rounds, round_timeout=round_timeout)
        if out_payload is not None and isinstance(out, dict):
            # Nur die informativen Felder durchreichen (kein exit-Code im payload).
            for key in ("stdout", "stderr", "summary", "loop_id", "rounds"):
                if key in out:
                    out_payload[key] = out[key]
        return int(out.get("exit", 1))
    except Exception as exc:  # noqa: BLE001  (Timeout, Subprozessfehler, …)
        msg = f"{type(exc).__name__}: {exc}"
        print(f"[job_poll] run_fn fehlgeschlagen für {item.job_id}: {msg}",
              file=sys.stderr)
        if out_payload is not None:
            out_payload["error"] = msg
        return 1


# --- Ein Tick: claim -> process -> publish -----------------------------------

def tick(source, run_fn=None, *, max_rounds: int = 4,
         round_timeout: int = 600) -> int:
    """Hole+arbeite EINEN Job ab. Return 1 wenn ein Job verarbeitet wurde, 0 wenn
    die Queue leer war.

    publish_result wird im finally GARANTIERT — HttpSource claimt serverseitig
    (queued->running); stirbt der Worker nach dem Claim ohne Result, bliebe der
    Job 'running' stranded (keine Stranded-Recovery wie in der Datei-Welt, nur der
    DCO-Lease-Tick nach TTL). result_status=None: der DCO mappt rc selbst auf den
    finalen Status (_EXIT_MAP, Single Source of Truth). result_payload ist
    informativ (gekürztes stdout/stderr)."""
    item = source.claim_next()
    if item is None:
        return 0
    rc = 1
    payload: dict = {}
    try:
        rc = process_item(item, run_fn=run_fn, max_rounds=max_rounds,
                           round_timeout=round_timeout, out_payload=payload)
    finally:
        try:
            source.publish_result(item, rc, result_payload=payload or None,
                                  result_status=None)
        except Exception as exc:  # noqa: BLE001
            print(f"[job_poll] publish_result fehlgeschlagen für {item.job_id}: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
    return 1


# --- Watch-Loop + CLI --------------------------------------------------------

# Eigener Singleton-Lock (NICHT der dual-bridge-poller.lock von handoff_poll und
# NICHT der dual-bridge-loop.lock von loop_driver) — sonst sperren sich die drei
# gegenseitig aus. Honoriert DUAL_BRIDGE_LOCK-Override in Tests.
_JOBPOLL_LOCK_NAME = "dual-bridge-jobpoll.lock"


def _jobpoll_lock_path():
    """Eigener Singleton-Lock-Pfad — NIE der geteilte default_lock_path().

    Mit DUAL_BRIDGE_LOCK-Override (Tests/CI) bleibt der Lock im selben
    Verzeichnis wie der geteilte Pfad (Isolation), bekommt aber einen
    job_poll-eigenen Dateinamen, damit sich job_poll, handoff_poll und
    loop_driver NICHT gegenseitig aussperren. Ohne Override: System-Tempdir."""
    from pathlib import Path
    import tempfile
    override = os.environ.get("DUAL_BRIDGE_LOCK")
    base = Path(override).parent if override else Path(tempfile.gettempdir())
    return base / _JOBPOLL_LOCK_NAME


def run_watch(source, *, run_fn=None, interval: int, max_rounds: int,
              round_timeout: int, tick_fn=None, sleep_fn=None) -> int:
    """Endlos-Loop: tick + Intervall-Backoff, bis KeyboardInterrupt. tick_fn und
    sleep_fn sind injizierbar (Tests). Liefert rc 0 bei sauberem Abbruch."""
    tick_fn = tick_fn or tick
    import time
    sleep_fn = sleep_fn or time.sleep
    try:
        while True:
            tick_fn(source, run_fn=run_fn, max_rounds=max_rounds,
                    round_timeout=round_timeout)
            sleep_fn(interval)
    except KeyboardInterrupt:
        print("[job_poll] Shutdown (KeyboardInterrupt).", file=sys.stderr)
        return 0


def _build_arg_parser():
    import argparse
    p = argparse.ArgumentParser(
        description="HTTP-Worker-Poll-Loop für den DCO-Job-Pull (Laptop B).")
    p.add_argument("--watch", action="store_true",
                   help="Endlos pollen (Default: ein Tick, dann Ende).")
    p.add_argument("--once", action="store_true",
                   help="Genau ein Tick (explizit; Default-Verhalten ohne --watch).")
    p.add_argument("--interval", type=int, default=15,
                   help="Sekunden zwischen Ticks im --watch-Modus (Default 15).")
    p.add_argument("--max-rounds", type=int, default=4,
                   help="An loop_driver durchgereicht (Default 4).")
    p.add_argument("--round-timeout", type=int, default=600,
                   help="An loop_driver durchgereicht (Default 600s).")
    return p


def main(argv=None, *, tick_fn=None, sleep_fn=None) -> int:
    """CLI-Einstieg. get_source() ist fail-closed (http ohne URL -> ValueError);
    wir fangen das und geben rc 2 (Config-Fehler), statt mit Traceback zu sterben.

    tick_fn/sleep_fn injizierbar (Tests laufen ohne Netz/Lock). Im echten Lauf
    (tick_fn is None) wird der Singleton-Lock geholt, damit nicht zwei Poller
    parallel claimen."""
    import bridge_transport as bt
    args = _build_arg_parser().parse_args(argv)

    try:
        source = bt.get_source()
    except ValueError as exc:
        print(f"[job_poll] Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2

    # Singleton-Lock nur im echten Lauf (nicht bei injiziertem Test-tick).
    if tick_fn is None:
        lock = _jobpoll_lock_path()
        if not bc.acquire_singleton_lock(lock):
            print("[job_poll] Ein job_poll läuft bereits — Abbruch.", file=sys.stderr)
            return 2

    if args.watch:
        return run_watch(source, run_fn=None, interval=args.interval,
                         max_rounds=args.max_rounds, round_timeout=args.round_timeout,
                         tick_fn=tick_fn, sleep_fn=sleep_fn)
    # Default / --once: ein Tick.
    _tick = tick_fn or tick
    _tick(source, run_fn=None, max_rounds=args.max_rounds,
          round_timeout=args.round_timeout)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
