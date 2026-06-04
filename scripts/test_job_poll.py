"""Tests für den HTTP-Worker-Poll-Loop (job_poll.py).

Dual-runnable wie der Rest der Suite:
    python -m pytest scripts/test_job_poll.py
    python scripts/test_job_poll.py

job_poll ist der fehlende Daemon, der den DCO-Job-Pull tatsächlich anschmeißt:
er holt über bridge_transport.get_source() (DUAL_BRIDGE_TRANSPORT=http) einen
Job aus dem DCO, arbeitet ihn über loop_driver (--mode goal-loop, run_fn) ab und
meldet das Ergebnis via source.publish_result zurück.

Isolation (kein Netz, kein Subprozess, kein Repo, kein echtes Drive):
  - HttpSource bekommt einen INJIZIERTEN Fake-Client (_FakeHttpClient).
  - Der Run-Pfad läuft über eine INJIZIERTE run_fn (_Runner), nie loop_driver.
  - conftest.py erzwingt tmp DUAL_BRIDGE_ROOT/LOCK + Drive-Poison-Guard.

Der Parser parse_input_text spiegelt den DCO-Parser bridge_router.parse_seed_line
byte-genau, mit GENAU EINER bewussten Abweichung: fehlendes repo= wirft NICHT
(Parser ist total), sondern liefert repo=None — die Fehler-Policy (rc 2) lebt in
process_item, nicht im Parser.
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path


def _fresh(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-jobpoll-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    os.environ["DUAL_BRIDGE_DEVICE"] = "testdev"
    os.environ.pop("DUAL_BRIDGE_TRANSPORT", None)
    os.environ.pop("DCO_BRIDGE_URL", None)
    os.environ.pop("DCO_BRIDGE_TOKEN", None)
    return root


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_transport as bt
    importlib.reload(bt)
    import job_poll as jp
    importlib.reload(jp)
    return bc, bt, jp


# ---------------------------------------------------------------------------
# (1) parse_input_text — reine, totale Funktion (spiegelt parse_seed_line)
# ---------------------------------------------------------------------------

def test_parse_full_header_extracts_all_fields():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text(
        "repo=https://x/y kind=implement adapter=codex\nBaue Feature Z\nDone: grün")
    assert parsed.repo == "https://x/y"
    assert parsed.kind == "implement"
    assert parsed.adapter == "codex"
    assert "Baue Feature Z" in parsed.seed
    assert "Done: grün" in parsed.seed


def test_parse_only_repo_uses_defaults():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text("repo=https://x/y\nnur ein ziel")
    assert parsed.repo == "https://x/y"
    assert parsed.kind == "implement"      # DCO-Default
    assert parsed.adapter == "codex"       # DCO-Default
    assert parsed.seed == "nur ein ziel"


def test_parse_missing_repo_yields_none_never_raises():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text("kind=implement\nkein repo hier")
    assert parsed.repo is None             # bewusste Abweichung vom DCO-Parser
    assert parsed.kind == "implement"
    assert parsed.seed == "kein repo hier"


def test_parse_empty_text_is_total():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text("   \n  ")
    assert parsed.repo is None
    assert parsed.seed == ""               # kein Wurf


def test_parse_multiline_seed_is_joined():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text("repo=https://x/y\nZeile 1\nZeile 2\nZeile 3")
    assert parsed.seed == "Zeile 1\nZeile 2\nZeile 3"


def test_parse_garbage_tokens_in_header_ignored():
    _fresh()
    _, _, jp = _reload()
    parsed = jp.parse_input_text("repo=https://x/y garbage noise=  \nziel")
    assert parsed.repo == "https://x/y"
    assert parsed.seed == "ziel"           # Tokens ohne = ignoriert, kein Wurf


# ---------------------------------------------------------------------------
# (1b) ensure_seed_structure — rohen Seed ins loop_driver-Format wrappen
# (loop_driver.parse_seed verlangt '## Ziel' + '## Done-Kriterien', sonst rc 2).
# Live-Bug 2026-06-04: roher Job-Seed -> "seed has no '## Ziel' block".
# ---------------------------------------------------------------------------

def _has_blocks(seed: str) -> bool:
    low = seed.lower()
    return "## ziel" in low and "## done-kriterien" in low


def test_ensure_seed_wraps_raw_text():
    _fresh()
    _, _, jp = _reload()
    out = jp.ensure_seed_structure("Lege Datei X an\nDone: X existiert")
    assert _has_blocks(out)
    assert "Lege Datei X an" in out
    # Done-Kriterium aus der Done:-Zeile übernommen
    assert "X existiert" in out


def test_ensure_seed_passes_structured_seed_through():
    """Ein bereits strukturierter Seed bleibt unverändert."""
    _fresh()
    _, _, jp = _reload()
    structured = "## Ziel\nBaue Y\n\n## Done-Kriterien\n- Y ist da"
    assert jp.ensure_seed_structure(structured) == structured


def test_ensure_seed_adds_fallback_criterion_when_no_done():
    """Ohne erkennbares Done-Kriterium -> generisches Fallback, damit
    loop_driver.parse_seed nicht an leeren Kriterien scheitert."""
    _fresh()
    _, _, jp = _reload()
    out = jp.ensure_seed_structure("Tu irgendwas Sinnvolles")
    assert _has_blocks(out)
    # mindestens ein Listenpunkt unter Done-Kriterien
    assert "\n- " in out


def test_ensure_seed_empty_still_has_blocks():
    _fresh()
    _, _, jp = _reload()
    out = jp.ensure_seed_structure("")
    assert _has_blocks(out)
    assert "\n- " in out


def test_process_item_wraps_seed_before_run_fn():
    """process_item übergibt run_fn einen strukturierten Seed (mit ## Ziel)."""
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "jw", "repo=https://x/y\nBaue Z\nDone: Z da")
    runner = _Runner(exit_code=0)
    jp.process_item(item, run_fn=runner, max_rounds=1, round_timeout=60)
    seed = runner.calls[0]["seed"]
    assert "## Ziel" in seed and "## Done-Kriterien" in seed


# ---------------------------------------------------------------------------
# Injizierbare Fakes (kein Netz, kein Subprozess, kein Repo)
# ---------------------------------------------------------------------------

class _Runner:
    """Injizierbare run_fn: liefert {"exit": rc} und protokolliert die Aufrufe.

    Signatur spiegelt job_poll._real_run_fn: keyword-only repo/seed/adapter/
    max_rounds/round_timeout. raise_for erzwingt einen Crash (Timeout-Simulation)."""
    def __init__(self, exit_code: int = 0, raise_exc: BaseException | None = None):
        self.exit_code = exit_code
        self.raise_exc = raise_exc
        self.calls: list[dict] = []

    def __call__(self, *, repo, seed, adapter, max_rounds, round_timeout) -> dict:
        self.calls.append({"repo": repo, "seed": seed, "adapter": adapter,
                           "max_rounds": max_rounds, "round_timeout": round_timeout})
        if self.raise_exc is not None:
            raise self.raise_exc
        return {"exit": self.exit_code, "loop_id": "loop-x", "rounds": 2,
                "stdout": "out", "stderr": ""}


def _work_item(bt, job_id: str, input_text: str):
    return bt.WorkItem(job_id=job_id, input_text=input_text, raw={})


class _FakeHttpClient:
    """Injizierbarer HTTP-Client (method, path, json, headers) -> (status, body).

    FIFO je Pfad-Präfix, protokolliert jeden Aufruf. Niemals echtes Netz —
    identisch zum Muster in test_bridge_transport.py."""
    def __init__(self, responses: dict[str, list[tuple[int, dict | None]]]):
        self._responses = {k: list(v) for k, v in responses.items()}
        self.calls: list[dict] = []

    def __call__(self, method, path, json=None, headers=None):
        self.calls.append({"method": method, "path": path, "json": json})
        for prefix, queue in self._responses.items():
            if path.startswith(prefix) and queue:
                return queue.pop(0)
        return (204, None)


def _http_source(bt, fake):
    return bt.HttpSource(base_url="http://test", token="tok",
                         worker_type="dual-bridge", client=fake)


# ---------------------------------------------------------------------------
# (2) process_item — WorkItem -> rc (parst input_text, ruft run_fn, kapselt)
# ---------------------------------------------------------------------------

def test_process_item_passes_repo_and_seed_to_run_fn():
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j1", "repo=https://github.com/dynamic-dome/x adapter=codex\nBaue X")
    runner = _Runner(exit_code=0)
    rc = jp.process_item(item, run_fn=runner, max_rounds=3, round_timeout=600)
    assert rc == 0
    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["repo"] == "https://github.com/dynamic-dome/x"
    assert "Baue X" in call["seed"]
    assert call["adapter"] == "codex"


def test_process_item_returns_rc_from_run_fn():
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j2", "repo=https://x/y\nziel")
    assert jp.process_item(item, run_fn=_Runner(exit_code=3),
                           max_rounds=3, round_timeout=600) == 3


def test_process_item_missing_repo_is_rc_2_without_running():
    """repo=None -> Config-Fehler rc 2, run_fn wird NICHT aufgerufen."""
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j3", "kind=implement\nkein repo")
    runner = _Runner(exit_code=0)
    rc = jp.process_item(item, run_fn=runner, max_rounds=3, round_timeout=600)
    assert rc == 2
    assert runner.calls == []              # nie gebaut ohne Repo


def test_process_item_run_crash_maps_to_rc_1():
    """run_fn wirft (Timeout/Subprozessfehler) -> gekapselt zu rc 1 (fail-soft)."""
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j4", "repo=https://x/y\nziel")
    runner = _Runner(raise_exc=TimeoutError("boom"))
    rc = jp.process_item(item, run_fn=runner, max_rounds=3, round_timeout=600)
    assert rc == 1


def test_process_item_fills_out_payload_with_run_output():
    """out_payload wird mit dem run_fn-Output befüllt (stdout/stderr/summary),
    damit der Fehlergrund nicht verloren geht (Live-Bug 2026-06-04)."""
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j5", "repo=https://x/y\nziel")
    runner = _Runner(exit_code=2)             # _Runner liefert stdout="out"
    out_payload: dict = {}
    rc = jp.process_item(item, run_fn=runner, max_rounds=3, round_timeout=600,
                         out_payload=out_payload)
    assert rc == 2
    assert out_payload.get("stdout") == "out"  # Output durchgereicht


def test_process_item_fills_out_payload_on_crash():
    """Auch bei run_fn-Crash bekommt out_payload eine Fehlerbeschreibung."""
    _fresh()
    _, bt, jp = _reload()
    item = _work_item(bt, "j6", "repo=https://x/y\nziel")
    runner = _Runner(raise_exc=RuntimeError("kaputt"))
    out_payload: dict = {}
    rc = jp.process_item(item, run_fn=runner, max_rounds=3, round_timeout=600,
                         out_payload=out_payload)
    assert rc == 1
    assert "kaputt" in (out_payload.get("error") or "")


# ---------------------------------------------------------------------------
# (3) tick — claim -> process -> publish (publish im finally garantiert)
# ---------------------------------------------------------------------------

def _posts(fake):
    return [c for c in fake.calls if c["method"] == "POST"]


def test_tick_claims_runs_and_publishes():
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({
        "/jobs/next": [(200, {"job_id": "j1",
                              "input_text": "repo=https://x/y\nBaue X"})],
        "/jobs/j1/result": [(200, {"ok": True})],
    })
    source = _http_source(bt, fake)
    runner = _Runner(exit_code=0)
    n = jp.tick(source, run_fn=runner)
    assert n == 1                          # ein Job verarbeitet
    assert len(runner.calls) == 1
    posts = _posts(fake)
    assert len(posts) == 1
    assert posts[0]["path"] == "/jobs/j1/result"
    assert posts[0]["json"]["rc"] == 0
    # Single Source of Truth = DCO _EXIT_MAP -> Worker erzwingt keinen Status.
    assert posts[0]["json"]["result_status"] is None


def test_tick_emits_progress_log():
    """tick gibt sichtbare Fortschritts-Meldungen aus (claim / build / result /
    publish), damit man auf B live sieht, was passiert. log_fn ist injizierbar."""
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({
        "/jobs/next": [(200, {"job_id": "jL",
                              "input_text": "repo=https://x/y\nBaue X\nDone: X da"})],
        "/jobs/jL/result": [(200, {"ok": True})],
    })
    source = _http_source(bt, fake)
    logs: list[str] = []
    jp.tick(source, run_fn=_Runner(exit_code=0), log_fn=logs.append)
    blob = " | ".join(logs).lower()
    assert "jl" in blob                    # Job-ID erscheint
    assert "aufgenommen" in blob or "claim" in blob
    assert "result" in blob or "rc" in blob or "fertig" in blob
    assert any("repo" in m.lower() or "x/y" in m for m in logs)  # Repo sichtbar


def test_tick_empty_queue_is_noop():
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({"/jobs/next": [(204, None)]})
    source = _http_source(bt, fake)
    runner = _Runner(exit_code=0)
    n = jp.tick(source, run_fn=runner)
    assert n == 0
    assert runner.calls == []              # nichts gebaut
    assert _posts(fake) == []              # nichts gemeldet


def test_tick_publishes_rc_from_run():
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({
        "/jobs/next": [(200, {"job_id": "j9", "input_text": "repo=https://x/y\nz"})],
        "/jobs/j9/result": [(200, {"ok": True})],
    })
    source = _http_source(bt, fake)
    jp.tick(source, run_fn=_Runner(exit_code=3))
    assert _posts(fake)[0]["json"]["rc"] == 3


def test_tick_publishes_run_output_as_payload():
    """tick schickt den run_fn-Output als result_payload mit (nicht None) —
    sonst geht die Fehlerursache im DCO verloren (Live-Bug 2026-06-04)."""
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({
        "/jobs/next": [(200, {"job_id": "jp", "input_text": "repo=https://x/y\nz"})],
        "/jobs/jp/result": [(200, {"ok": True})],
    })
    source = _http_source(bt, fake)
    jp.tick(source, run_fn=_Runner(exit_code=2))   # _Runner: stdout="out"
    payload = _posts(fake)[0]["json"]["result_payload"]
    assert payload is not None
    assert payload.get("stdout") == "out"


def test_tick_publishes_even_when_run_crashes():
    """run_fn wirft -> Job wird NICHT stranded: tick published trotzdem rc 1.
    (HttpSource hat keine Stranded-Recovery wie die Datei-Welt.)"""
    _fresh()
    _, bt, jp = _reload()
    fake = _FakeHttpClient({
        "/jobs/next": [(200, {"job_id": "jc", "input_text": "repo=https://x/y\nz"})],
        "/jobs/jc/result": [(200, {"ok": True})],
    })
    source = _http_source(bt, fake)
    jp.tick(source, run_fn=_Runner(raise_exc=TimeoutError("boom")))
    posts = _posts(fake)
    assert len(posts) == 1                 # publish trotz Crash
    assert posts[0]["json"]["rc"] == 1


# ---------------------------------------------------------------------------
# (4) main — argparse, --once / --watch / --interval, fail-closed get_source
# ---------------------------------------------------------------------------

def test_main_once_runs_single_tick():
    """--once mit DUAL_BRIDGE_TRANSPORT=http + URL: genau ein Tick, rc 0."""
    _fresh()
    _, bt, jp = _reload()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    os.environ["DCO_BRIDGE_URL"] = "http://test/api"
    os.environ["DCO_BRIDGE_TOKEN"] = "tok"
    ticks = {"n": 0}
    def fake_tick(source, **kw):
        ticks["n"] += 1
        return 0
    rc = jp.main(["--once"], tick_fn=fake_tick)
    assert rc == 0
    assert ticks["n"] == 1


def test_main_http_without_url_returns_2():
    """get_source() ist fail-closed: http ohne DCO_BRIDGE_URL -> rc 2 (Config),
    kein Traceback."""
    _fresh()
    _, bt, jp = _reload()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    os.environ.pop("DCO_BRIDGE_URL", None)
    rc = jp.main(["--once"], tick_fn=lambda *a, **k: 0)
    assert rc == 2


def test_main_watch_loops_until_stop():
    """--watch tickt wiederholt und endet sauber, wenn das Stop-Signal kommt."""
    _fresh()
    _, bt, jp = _reload()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    os.environ["DCO_BRIDGE_URL"] = "http://test/api"
    state = {"n": 0}
    def fake_tick(source, **kw):
        state["n"] += 1
        if state["n"] >= 3:
            raise KeyboardInterrupt       # simuliert Ctrl-C / Shutdown
        return 0
    sleeps: list = []
    rc = jp.main(["--watch", "--interval", "7"], tick_fn=fake_tick,
                 sleep_fn=sleeps.append)
    assert state["n"] == 3                 # 3 Ticks, dann sauberer Abbruch
    assert rc == 0
    assert sleeps and sleeps[0] == 7       # Backoff/Intervall genutzt


# ---------------------------------------------------------------------------
# (5) Singleton-Lock: eigener Pfad, NIE der geteilte handoff_poll/loop_driver-Lock
# ---------------------------------------------------------------------------

def test_jobpoll_lock_path_differs_from_shared_lock_with_override():
    """Mit gesetztem DUAL_BRIDGE_LOCK (geteilter Pfad von handoff_poll/loop_driver)
    MUSS job_poll trotzdem einen EIGENEN Lock-Dateinamen wählen — sonst sperren
    sich die Daemons gegenseitig aus. Der Lock bleibt im selben Verzeichnis
    (Test-Isolation), aber mit job_poll-eigenem Namen."""
    _fresh()
    bc, _, jp = _reload()
    shared = Path(tempfile.mkdtemp(prefix="bridge-lock-")) / "poller.lock"
    os.environ["DUAL_BRIDGE_LOCK"] = str(shared)
    bc, _, jp = _reload()
    own = jp._jobpoll_lock_path()
    assert own != shared                       # NICHT der geteilte Lock
    assert own.name == "dual-bridge-jobpoll.lock"
    assert own.parent == shared.parent         # selbes Verzeichnis (Isolation bleibt)


def test_jobpoll_lock_path_without_override_uses_tempdir():
    """Ohne Override: eigener Lock im System-Tempdir (kein geteilter Pfad)."""
    _fresh()
    bc, _, jp = _reload()
    os.environ.pop("DUAL_BRIDGE_LOCK", None)
    bc, _, jp = _reload()
    own = jp._jobpoll_lock_path()
    assert own.name == "dual-bridge-jobpoll.lock"
    assert own.parent == Path(tempfile.gettempdir())


def test_main_aborts_when_jobpoll_lock_already_held():
    """Echter Lock-Pfad (tick_fn=None -> Lock-Block laeuft): haelt ein lebender
    job_poll den Lock, bricht ein zweiter main() mit rc 2 ab. Deckt den zuvor
    ungetesteten Lock-Block in main() ab."""
    _fresh()
    bc, bt, jp = _reload()
    os.environ["DUAL_BRIDGE_TRANSPORT"] = "http"
    os.environ["DCO_BRIDGE_URL"] = "http://test/api"
    lock_dir = Path(tempfile.mkdtemp(prefix="bridge-lock-"))
    os.environ["DUAL_BRIDGE_LOCK"] = str(lock_dir / "poller.lock")
    bc, bt, jp = _reload()
    # Einen LEBENDEN Fremd-Lock auf dem job_poll-Pfad simulieren (anderer PID).
    own = jp._jobpoll_lock_path()
    own.parent.mkdir(parents=True, exist_ok=True)
    own.write_text("999999999\n2026-01-01T00:00:00\n", encoding="utf-8")
    # 999999999 ist (praktisch sicher) kein lebender PID -> waere STALE und wuerde
    # uebernommen. Wir patchen _pid_alive, damit der Fremd-Lock als LEBEND gilt.
    orig_alive = bc._pid_alive
    bc._pid_alive = lambda pid: True
    try:
        rc = jp.main(["--once"])           # tick_fn=None -> echter Lock-Block
    finally:
        bc._pid_alive = orig_alive
    assert rc == 2                          # Lock belegt -> sauberer Abbruch


# ---------------------------------------------------------------------------
# Dual-runnable Footer
# ---------------------------------------------------------------------------

def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    print(f"job_poll: {len(tests)} Tests")
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(_run_all())
