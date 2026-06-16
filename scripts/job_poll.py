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

import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import bridge_common as bc
import risk_policy


_LOOP_ID_MARKER_RE = re.compile(r"loop_id=(loop-[A-Za-z0-9_-]+)")


def _parse_loop_id(stdout: str) -> str | None:
    """Die von loop_driver._next_loop_id frueh gedruckte loop_id aus dem VOLLEN
    stdout lesen — vor der 2000-Zeichen-Kuerzung des Tails (sonst geht der frueh
    gedruckte Marker bei langen Builds verloren)."""
    m = _LOOP_ID_MARKER_RE.search(stdout or "")
    return m.group(1) if m else None


def write_heartbeat(now: str | None = None):
    """B-Worker-Liveness: schreibt lane-B-to-A/_worker-heartbeat.json — ein echtes
    Drive-Artefakt, das die DCO-Ops-Konsole liest. Fail-soft: ein Drive-Fehler
    darf den Worker NIE killen."""
    try:
        path = bc.lane_root("B-to-A") / "_worker-heartbeat.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            endpoint = bc.this_endpoint()
        except Exception:  # noqa: BLE001  (unbekannter Host ohne Override)
            endpoint = None
        payload = {
            "ts": now or bc.now_iso(),
            "endpoint": endpoint,
            "host": socket.gethostname(),
            "pid": os.getpid(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path
    except Exception:  # noqa: BLE001
        return None


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

def _stream_reader(pipe, echo_stream, sink: list) -> None:
    """Liest einen Subprozess-Stream zeilenweise, echoot LIVE auf echo_stream und
    sammelt die Zeilen in sink (für den späteren result_payload-Tail). Läuft je
    Stream in einem eigenen Thread -> vermeidet den klassischen PIPE-Deadlock,
    wenn ein Stream den OS-Puffer füllt, während wir am anderen lesen."""
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            sink.append(line)
            echo_stream.write(line)
            echo_stream.flush()
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _as_bool(v) -> bool:
    """Parse a config/env flag to bool. config_value passes the env string or the
    already-typed fallback (False); '1'/'true'/'yes'/'on' (any case) are true,
    everything else — including '0'/'false'/'' — is false."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _real_run_fn(*, repo: str, seed: str, adapter: str,
                 max_rounds: int, round_timeout: int, stream: bool = False) -> dict:
    """Default-Runner: ruft loop_driver.py --mode goal-loop als Subprozess auf
    (gehärtetes Env, UTF-8-Runtime). Gibt {'exit': rc, ...} zurück. Wirft bei
    Timeout — der Aufrufer (process_item) wertet das als rc 1 (fail-soft).

    Spiegelt bridge_overnight._real_run_fn (gleiches cmd, gleicher Wall-Clock-Cap,
    gleicher {'exit': ...}-Vertrag), getriggert durch einen geclaimten HTTP-Job
    statt durch eine Seed-Queue. adapter wird an loop_driver durchgereicht.

    stream=False (Default): subprocess.run mit capture_output — Output erst am
    Ende, ideal für den stillen Daemon-Betrieb (unverändertes Verhalten).
    stream=True: subprocess.Popen + zwei Reader-Threads, die stdout/stderr LIVE
    auf die Konsole echoen (getrennt) UND je einen Tail puffern -> man sieht den
    Build mitlaufen, der result_payload bleibt aber erhalten. Wall-Clock-Cap
    (round_timeout*max_rounds+120) gilt in beiden Pfaden; bei Überschreitung wird
    der Prozess gekillt und TimeoutExpired geworfen (fail-soft im Aufrufer)."""
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
    # Opt-in cross-package accumulation: when DUAL_BRIDGE_MERGE_ON_ACCEPT is set
    # (env > config.json key 'merge_on_accept' > off), an accepted build is merged
    # into base so the next dependent package's fresh clone sees it. Off by default
    # — a single independent job must not silently push to the target repo's base.
    if bc.config_value("merge_on_accept", "DUAL_BRIDGE_MERGE_ON_ACCEPT", False,
                       cast=_as_bool):
        cmd.append("--merge-on-accept")
    cap = round_timeout * max_rounds + 120
    if not stream:
        proc = subprocess.run(
            cmd, cwd=str(Path(__file__).parent),
            env=bc.safe_subprocess_env(),
            # loop_driver emits UTF-8 (em-dash etc.). Without an explicit
            # encoding, text=True decodes with the Windows locale (CP1252) and
            # mangles "—" into "â€"" — which then lands double-encoded in the
            # DCO verdict. errors="replace" keeps a single bad byte from crashing.
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=cap,
        )
        full_out = proc.stdout or ""
        out = {"exit": proc.returncode, "stdout": full_out[-2000:],
               "stderr": (proc.stderr or "")[-2000:]}
        lid = _parse_loop_id(full_out)
        if lid:
            out["loop_id"] = lid
        return out

    # Live-Stream: Popen + Tee. stdout/stderr getrennt halten (eigene Threads).
    import threading
    proc = subprocess.Popen(
        cmd, cwd=str(Path(__file__).parent),
        env=bc.safe_subprocess_env(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        # Same UTF-8 pin as the stream=False path above (Windows CP1252 mojibake).
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    out_lines: list[str] = []
    err_lines: list[str] = []
    t_out = threading.Thread(target=_stream_reader,
                             args=(proc.stdout, sys.stdout, out_lines), daemon=True)
    t_err = threading.Thread(target=_stream_reader,
                             args=(proc.stderr, sys.stderr, err_lines), daemon=True)
    t_out.start()
    t_err.start()
    try:
        rc = proc.wait(timeout=cap)
    except subprocess.TimeoutExpired:
        proc.kill()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        raise
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    full_out = "".join(out_lines)
    out = {"exit": rc, "stdout": full_out[-2000:],
           "stderr": "".join(err_lines)[-2000:]}
    lid = _parse_loop_id(full_out)
    if lid:
        out["loop_id"] = lid
    return out


def _run_fn_accepts_stream(run_fn) -> bool:
    """True, wenn run_fn ein 'stream'-Keyword (oder **kwargs) akzeptiert. So reichen
    wir stream nur an passende Runner durch und brechen ältere/injizierte run_fns
    (ohne stream) nicht."""
    import inspect
    try:
        params = inspect.signature(run_fn).parameters
    except (TypeError, ValueError):
        return False
    if "stream" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def process_item(item, run_fn=None, *, max_rounds: int = 4,
                 round_timeout: int = 600, out_payload: dict | None = None,
                 stream: bool = False) -> int:
    """Arbeite einen geclaimten WorkItem ab und liefere den rc.

    parst item.input_text -> (repo, seed, adapter). Fehlt repo -> rc 2 (Config-
    Fehler), ohne run_fn aufzurufen. Risk-Policy-Verstoss (risk_policy.check_task,
    z.B. Ops-Verb im Seed) -> ebenfalls rc 2 ohne run_fn, Grund in
    out_payload['error'] mit Praefix 'risk_policy:'. Sonst run_fn(...) -> {'exit': rc}; ein Crash/
    Timeout aus run_fn wird zu rc 1 gekapselt (fail-soft, damit ein kaputter Job
    den Loop nie killt). Der DCO mappt rc selbst auf den finalen Status.

    out_payload (optional, in-place gefüllt): bekommt den run_fn-Output bzw. eine
    Fehlerbeschreibung, damit die Ursache NICHT verloren geht (Live-Bug 2026-06-04:
    ein fehlgeschlagener Job zeigte im DCO nur 'error' ohne stdout/stderr).

    stream wird an run_fn nur durchgereicht, wenn dessen Signatur es akzeptiert
    (Default-_real_run_fn ja; ältere injizierte run_fns ohne stream bleiben heil)."""
    run_fn = run_fn or _real_run_fn
    parsed = parse_input_text(item.input_text)
    if parsed.repo is None:
        if out_payload is not None:
            out_payload["error"] = "config: seed ohne repo= (rc 2)"
        return 2
    violation = risk_policy.check_task(parsed.kind, parsed.adapter, parsed.seed)
    if violation is not None:
        if out_payload is not None:
            out_payload["error"] = (
                f"risk_policy:{violation.rule}: {violation.reason} (rc 2)")
        return 2
    try:
        seed = ensure_seed_structure(parsed.seed)
        extra = {"stream": stream} if _run_fn_accepts_stream(run_fn) else {}
        out = run_fn(repo=parsed.repo, seed=seed, adapter=parsed.adapter,
                     max_rounds=max_rounds, round_timeout=round_timeout, **extra)
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

def _default_log(msg: str) -> None:
    """Default-Progress-Logger: Zeitstempel + Zeile auf stdout (sofort geflusht,
    damit man auf B live mitliest)."""
    from datetime import datetime
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# rc -> menschenlesbares Outcome (nur für die Log-Ausgabe; der DCO mappt selbst).
_RC_LABEL = {0: "accepted", 3: "escalated", 2: "config/resume-error", 1: "error"}


def tick(source, run_fn=None, *, max_rounds: int = 4,
         round_timeout: int = 600, log_fn=None, stream: bool = False) -> int:
    """Hole+arbeite EINEN Job ab. Return 1 wenn ein Job verarbeitet wurde, 0 wenn
    die Queue leer war.

    log_fn(msg) (injizierbar, Default _default_log) gibt sichtbaren Fortschritt
    aus: Job aufgenommen / Build startet / fertig mit rc / zurückgemeldet — damit
    man auf B live sieht, was passiert.

    publish_result wird im finally GARANTIERT — HttpSource claimt serverseitig
    (queued->running); stirbt der Worker nach dem Claim ohne Result, bliebe der
    Job 'running' stranded (keine Stranded-Recovery wie in der Datei-Welt, nur der
    DCO-Lease-Tick nach TTL). result_status=None: der DCO mappt rc selbst auf den
    finalen Status (_EXIT_MAP, Single Source of Truth). result_payload ist
    informativ (gekürztes stdout/stderr)."""
    log = log_fn or _default_log
    item = source.claim_next()
    if item is None:
        return 0
    parsed = parse_input_text(item.input_text)
    repo = parsed.repo or "(kein repo!)"
    log(f"Job aufgenommen: {item.job_id} — repo={repo} adapter={parsed.adapter}")
    log(f"  Build startet (loop_driver, max_rounds={max_rounds}, "
        f"round_timeout={round_timeout}s{', live-stream' if stream else ''}) — das kann dauern…")
    rc = 1
    payload: dict = {}
    try:
        rc = process_item(item, run_fn=run_fn, max_rounds=max_rounds,
                           round_timeout=round_timeout, out_payload=payload,
                           stream=stream)
        log(f"  Build fertig: rc={rc} ({_RC_LABEL.get(rc, '?')})")
    finally:
        try:
            source.publish_result(item, rc, result_payload=payload or None,
                                  result_status=None)
            log(f"  Ergebnis an DCO zurückgemeldet (Job {item.job_id}, rc={rc}).")
        except Exception as exc:  # noqa: BLE001
            log(f"  WARN: publish_result fehlgeschlagen für {item.job_id}: "
                f"{type(exc).__name__}: {exc}")
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
              round_timeout: int, tick_fn=None, sleep_fn=None,
              stream: bool = False) -> int:
    """Endlos-Loop: tick + Intervall-Backoff, bis KeyboardInterrupt. tick_fn und
    sleep_fn sind injizierbar (Tests). Liefert rc 0 bei sauberem Abbruch.

    stream wird an tick_fn nur durchgereicht, wenn dessen Signatur es akzeptiert
    (das echte tick ja; ältere injizierte tick_fns ohne stream bleiben heil)."""
    tick_fn = tick_fn or tick
    import time
    sleep_fn = sleep_fn or time.sleep
    tick_extra = {"stream": stream} if _run_fn_accepts_stream(tick_fn) else {}
    _default_log(f"Worker läuft (--watch, alle {interval}s). Warte auf Jobs… (Ctrl-C beendet)")
    idle = 0
    try:
        while True:
            write_heartbeat()  # b1: Liveness-Artefakt je Poll-Iteration (fail-soft)
            n = tick_fn(source, run_fn=run_fn, max_rounds=max_rounds,
                        round_timeout=round_timeout, **tick_extra)
            if n:
                idle = 0
            else:
                idle += 1
                # Lebenszeichen ca. alle ~5 Leerläufe, damit man sieht: lebt, Queue leer.
                if idle % 5 == 1:
                    _default_log(f"…Queue leer, poll weiter (Leerlauf {idle}).")
            sleep_fn(interval)
    except KeyboardInterrupt:
        _default_log("Shutdown (Ctrl-C).")
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
    p.add_argument("--stream", action="store_true",
                   help="loop_driver-Output LIVE auf die Konsole streamen "
                        "(alternativ DUAL_BRIDGE_STREAM=1). Default: still.")
    return p


def main(argv=None, *, tick_fn=None, sleep_fn=None, source_override=None) -> int:
    """CLI-Einstieg. get_source() ist fail-closed (http ohne URL -> ValueError);
    wir fangen das und geben rc 2 (Config-Fehler), statt mit Traceback zu sterben.

    tick_fn/sleep_fn injizierbar (Tests laufen ohne Netz/Lock). source_override
    erlaubt Tests, eine fertige Source einzuspeisen (kein get_source/Lock). Im
    echten Lauf (tick_fn is None) wird der Singleton-Lock geholt, damit nicht zwei
    Poller parallel claimen.

    Live-Stream: --stream-Flag ODER DUAL_BRIDGE_STREAM=1 -> loop_driver-Output
    läuft live über die Konsole (statt erst am Ende gesammelt)."""
    import bridge_transport as bt
    args = _build_arg_parser().parse_args(argv)
    stream = bool(args.stream) or os.environ.get("DUAL_BRIDGE_STREAM") == "1"

    if source_override is not None:
        source = source_override
    else:
        try:
            source = bt.get_source()
        except ValueError as exc:
            print(f"[job_poll] Konfigurationsfehler: {exc}", file=sys.stderr)
            return 2

    # Singleton-Lock nur im echten Lauf (nicht bei injiziertem Test-tick/Source).
    if tick_fn is None and source_override is None:
        lock = _jobpoll_lock_path()
        if not bc.acquire_singleton_lock(lock, must_match="job_poll"):
            print("[job_poll] Ein job_poll läuft bereits — Abbruch.", file=sys.stderr)
            return 2

    if args.watch:
        return run_watch(source, run_fn=None, interval=args.interval,
                         max_rounds=args.max_rounds, round_timeout=args.round_timeout,
                         tick_fn=tick_fn, sleep_fn=sleep_fn, stream=stream)
    # Default / --once: ein Tick.
    _tick = tick_fn or tick
    _tick_extra = {"stream": stream} if _run_fn_accepts_stream(_tick) else {}
    _tick(source, run_fn=None, max_rounds=args.max_rounds,
          round_timeout=args.round_timeout, **_tick_extra)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
