"""Tests für den Overnight-Scheduler (bridge_overnight.py).

Dual-runnable wie der Rest der Suite:
    python -m pytest scripts/test_bridge_overnight.py
    python scripts/test_bridge_overnight.py

Isoliert über DUAL_BRIDGE_STATE (tmp) und ein tmp-Queue-Verzeichnis. Es wird NIE
ein echter goal-loop gestartet — die Ausführung läuft über eine injizierte run_fn,
sodass kein Test je einen Subprozess, das Netz oder ein Repo berührt. Der Versand
des Digests läuft über eine injizierte send_fn (kein Telegram).

Der Scheduler ist eine read-mostly Batch-Kante: er liest Seeds aus der Queue, ruft
je Seed run_fn auf, mappt den Exit-Code auf ein Outcome und schreibt EINEN
Run-Record nach state/_overnight/runs/. Den Digest baut/sendet der Notifier.
"""
from __future__ import annotations

import importlib
import json
import os
import tempfile
from pathlib import Path


def _fresh(endpoint: str = "claude@laptop-a") -> tuple[Path, Path]:
    root = Path(tempfile.mkdtemp(prefix="bridge-overnight-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    os.environ["DUAL_BRIDGE_STATE"] = str(root / "state")
    os.environ["TELEGRAM_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "4242"
    os.environ.pop("DUAL_BRIDGE_TG_TOKEN", None)
    os.environ.pop("DUAL_BRIDGE_TG_CHAT", None)
    queue = root / "queue"
    queue.mkdir(parents=True, exist_ok=True)
    return root, queue


def _reload():
    import bridge_common as bc
    importlib.reload(bc)
    import bridge_status as bs
    importlib.reload(bs)
    import bridge_notify as bn
    importlib.reload(bn)
    import bridge_overnight as bo
    importlib.reload(bo)
    return bc, bs, bn, bo


def _seed(queue: Path, name: str, goal: str = "Tu etwas Sinnvolles") -> Path:
    p = queue / name
    p.write_text(
        f"## Ziel\n{goal}\n\n## Done-Kriterien\n- Kriterium A\n- Kriterium B\n",
        encoding="utf-8")
    return p


class _Runner:
    """Injizierbare run_fn: ordnet jedem Seed-Dateinamen einen Exit-Code zu und
    protokolliert die Aufrufreihenfolge. Default-Exit 0 (accepted)."""
    def __init__(self, exits: dict | None = None, default: int = 0,
                 raise_for: set | None = None):
        self.exits = exits or {}
        self.default = default
        self.raise_for = raise_for or set()
        self.calls: list[str] = []          # Dateinamen in Aufrufreihenfolge

    def __call__(self, *, seed_file: Path, seed_text: str, goal: str,
                 repo: str, max_rounds: int, round_timeout: int) -> dict:
        name = seed_file.name
        self.calls.append(name)
        if name in self.raise_for:
            raise TimeoutError(f"simulierter Timeout für {name}")
        rc = self.exits.get(name, self.default)
        return {"exit": rc, "loop_id": f"loop-{name}", "rounds": 2}


class _Recorder:
    """Injizierbare send_fn für den Digest — protokolliert nur."""
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, text: str) -> None:
        self.calls.append(text)


def _latest_run_record(bs) -> dict | None:
    runs = bs.STATE_DIR / "_overnight" / "runs"
    if not runs.exists():
        return None
    files = sorted(runs.glob("*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


# --- (1) leere/fehlende Queue -> 0 Seeds ------------------------------------
def test_empty_queue_does_nothing_but_reports() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    runner = _Runner()
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           run_fn=runner, send_fn=rec)
    assert runner.calls == [], "leere Queue darf keinen Loop starten"
    assert res.summary["total"] == 0, res.summary
    assert len(rec.calls) == 1, "auch bei leerer Queue genau ein Digest"
    rracord = _latest_run_record(bs)
    assert rracord and rracord["summary"]["total"] == 0
    print("  overnight OK — leere Queue: nichts gestartet, Digest 'nichts zu tun'")


# --- (2) Reihenfolge alphabetisch; .skip und _done/ ignoriert ---------------
def test_queue_order_and_skips() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "02-bravo.md")
    _seed(queue, "01-alpha.md")
    _seed(queue, "03-charlie.md.skip")          # deaktiviert
    (queue / "_done").mkdir()
    _seed(queue / "_done", "00-old.md")          # bereits erledigt
    runner = _Runner()
    rec = _Recorder()
    bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                     run_fn=runner, send_fn=rec)
    assert runner.calls == ["01-alpha.md", "02-bravo.md"], runner.calls
    print("  overnight OK — alphabetische Reihenfolge, .skip und _done/ ignoriert")


# --- (3) Exit-Mapping 0/3/2/1 -> accepted/escalated/error -------------------
def test_exit_code_mapping() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    _seed(queue, "02-esc.md")
    _seed(queue, "03-cfg.md")
    _seed(queue, "04-err.md")
    runner = _Runner(exits={"01-ok.md": 0, "02-esc.md": 3,
                            "03-cfg.md": 2, "04-err.md": 1})
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           run_fn=runner, send_fn=rec)
    by = {s["file"]: s["outcome"] for s in res.seeds}
    assert by == {"01-ok.md": "accepted", "02-esc.md": "escalated",
                  "03-cfg.md": "error", "04-err.md": "error"}, by
    assert res.summary == {"accepted": 1, "escalated": 1, "error": 2, "total": 4}
    print("  overnight OK — Exit 0/3/2/1 -> accepted/escalated/error/error")


# --- (4) ein Fehler bricht den Batch NICHT ab -------------------------------
def test_failing_seed_does_not_abort_batch() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    _seed(queue, "02-boom.md")
    _seed(queue, "03-after.md")
    runner = _Runner(exits={"01-ok.md": 0, "03-after.md": 0},
                     raise_for={"02-boom.md"})
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           run_fn=runner, send_fn=rec)
    assert runner.calls == ["01-ok.md", "02-boom.md", "03-after.md"], runner.calls
    by = {s["file"]: s["outcome"] for s in res.seeds}
    assert by["02-boom.md"] == "error", by
    assert by["03-after.md"] == "accepted", "Seed nach dem Fehler muss laufen"
    print("  overnight OK — fehlschlagender Seed isoliert, Batch läuft weiter")


# --- (5) --dry-run: kein run_fn, kein Send, kein State ----------------------
def test_dry_run_is_side_effect_free() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    runner = _Runner()
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           run_fn=runner, send_fn=rec, dry_run=True)
    assert runner.calls == [], "dry-run darf keinen Loop starten"
    assert rec.calls == [], "dry-run darf nichts senden"
    assert _latest_run_record(bs) is None, "dry-run darf keinen State schreiben"
    assert res.summary["total"] == 1, "dry-run plant 1 Seed (zählt, startet nicht)"
    print("  overnight OK — --dry-run plant nur, ohne Lauf/Send/State")


# --- (6) State-Record korrekt + atomar; Sidecar isoliert -------------------
def test_state_record_written() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    runner = _Runner(exits={"01-ok.md": 0})
    rec = _Recorder()
    bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                     run_fn=runner, send_fn=rec)
    rracord = _latest_run_record(bs)
    assert rracord is not None, "es muss ein Run-Record geschrieben werden"
    assert {"started", "finished", "seeds", "summary"} <= set(rracord), rracord
    assert rracord["seeds"][0]["file"] == "01-ok.md"
    assert rracord["seeds"][0]["exit"] == 0
    assert rracord["seeds"][0]["outcome"] == "accepted"
    # Sidecar liegt unter _overnight/, nicht etwa im _notify/-Baum
    assert (bs.STATE_DIR / "_overnight" / "runs").exists()
    assert not (bs.STATE_DIR / "_notify").exists(), "kein Leak in _notify/"
    print("  overnight OK — Run-Record vollständig + im eigenen Sidecar")


# --- (7) Digest-Format + --no-notify ----------------------------------------
def test_digest_format_and_no_notify() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    _seed(queue, "02-esc.md")
    runner = _Runner(exits={"01-ok.md": 0, "02-esc.md": 3})
    # (a) Digest wird gesendet und enthält die Kernzahlen + Seed-Namen
    rec = _Recorder()
    bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                     run_fn=runner, send_fn=rec)
    assert len(rec.calls) == 1, rec.calls
    msg = rec.calls[0]
    assert "01-ok.md" in msg and "02-esc.md" in msg, msg
    assert "accepted" in msg.lower() or "1" in msg, msg
    # (b) --no-notify unterdrückt den Send, der State bleibt trotzdem
    root2, queue2 = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue2, "01-ok.md")
    runner2 = _Runner()
    rec2 = _Recorder()
    bo.run_overnight(queue_dir=queue2, repo="https://x/y", max_rounds=3,
                     run_fn=runner2, send_fn=rec2, notify=False)
    assert rec2.calls == [], "--no-notify darf nicht senden"
    assert _latest_run_record(bs) is not None, "State trotzdem schreiben"
    print("  overnight OK — Digest enthält Seeds+Zahlen; --no-notify unterdrückt Send")


# --- (8) Config-Guard: nicht-leere Queue ohne --repo -> Exit 2 --------------
def test_config_guard_requires_repo() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-ok.md")
    runner = _Runner()
    # main() ohne --repo bei nicht-leerer Queue
    rc = bo.main(["--queue", str(queue)], run_fn=runner, send_fn=_Recorder())
    assert rc == 2, rc
    assert runner.calls == [], "ohne --repo darf nichts starten"
    assert _latest_run_record(bs) is None, "fail-closed: kein State bei Fehlkonfig"
    print("  overnight OK — nicht-leere Queue ohne --repo: Exit 2, nichts gestartet")


# --- (9) Subprozess-Timeout je Seed -> error, Batch läuft weiter ------------
def test_seed_timeout_counts_as_error() -> None:
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    _seed(queue, "01-slow.md")
    _seed(queue, "02-ok.md")
    runner = _Runner(exits={"02-ok.md": 0}, raise_for={"01-slow.md"})
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           round_timeout=1, run_fn=runner, send_fn=rec)
    by = {s["file"]: s["outcome"] for s in res.seeds}
    assert by["01-slow.md"] == "error", by
    assert by["02-ok.md"] == "accepted", by
    print("  overnight OK — Seed-Timeout zählt als error, Folge-Seed läuft")


# --- (10) Nicht-Seed-Dateien (README.md, Doku ohne '## Ziel') ausschließen ---
def test_non_seed_files_excluded() -> None:
    """Eine *.md ohne '## Ziel'-Block ist kein Seed (z.B. die README.md der Queue).
    Sie darf NIE als goal-loop gestartet werden — sonst eskaliert jeder Lauf an
    der Doku. Regression für den dry-run-Befund 2026-06-03 (README als Seed)."""
    root, queue = _fresh()
    bc, bs, bn, bo = _reload()
    # echte Seeds (mit ## Ziel) + zwei Nicht-Seeds (README + reine Doku)
    _seed(queue, "01-real.md")
    _seed(queue, "02-also-real.md")
    # Die ECHTE Queue-README enthält einen '## Ziel'-Block als Format-Beispiel —
    # genau das schlüpfte durch eine reine '## Ziel'-Heuristik. Hier reproduziert.
    (queue / "README.md").write_text(
        "# Overnight-Queue\nFormat-Beispiel:\n\n## Ziel\n<dein Ziel>\n\n"
        "## Done-Kriterien\n- <Kriterium>\n", encoding="utf-8")
    (queue / "NOTES.md").write_text(
        "Irgendeine Notiz ohne Zielblock.\n", encoding="utf-8")
    runner = _Runner()
    rec = _Recorder()
    res = bo.run_overnight(queue_dir=queue, repo="https://x/y", max_rounds=3,
                           run_fn=runner, send_fn=rec)
    assert runner.calls == ["01-real.md", "02-also-real.md"], runner.calls
    assert res.summary["total"] == 2, res.summary
    # discover_seeds selbst liefert ebenfalls nur die echten Seeds
    names = [p.name for p in bo.discover_seeds(queue)]
    assert names == ["01-real.md", "02-also-real.md"], names
    print("  overnight OK — README.md/Doku ohne '## Ziel' sind keine Seeds")


# --- (11) Default-Queue ist repo-relativ, nicht CWD-relativ -----------------
def test_default_queue_resolves_from_repo_root(monkeypatch=None) -> None:
    """discover_seeds mit dem Default-Verzeichnis muss die Repo-Queue finden,
    egal aus welchem CWD der Scheduler gestartet wird (manuell aus scripts/ vs.
    registrierter Task aus der Repo-Wurzel). Regression für den CWD-Befund."""
    import os as _os
    bc, bs, bn, bo = _reload()
    repo_root = Path(bo.__file__).resolve().parent.parent
    real_queue = repo_root / bo.DEFAULT_QUEUE
    # Es muss eine auflösbare Default-Queue geben, die NICHT vom CWD abhängt.
    resolved = bo.default_queue_dir()
    assert resolved == real_queue, (resolved, real_queue)
    # …und sie bleibt dieselbe, egal aus welchem Arbeitsverzeichnis.
    old = _os.getcwd()
    try:
        _os.chdir(str(repo_root / "scripts"))
        assert bo.default_queue_dir() == real_queue, bo.default_queue_dir()
        _os.chdir(str(repo_root))
        assert bo.default_queue_dir() == real_queue, bo.default_queue_dir()
    finally:
        _os.chdir(old)
    print("  overnight OK — Default-Queue repo-relativ, CWD-unabhängig")


# --- (11b) main() OHNE --queue nutzt die repo-relative Default-Queue ----------
def test_main_without_queue_uses_default(monkeypatch=None) -> None:
    """main() ohne --queue muss die ECHTE repo-relative docs/overnight finden —
    egal aus welchem CWD. Schließt die Lücke, dass nur default_queue_dir() direkt
    getestet ist (Codex-MINOR 2026-06-03): die Verdrahtung in main() selbst.
    Läuft mit injizierter run_fn (kein echter Loop)."""
    import os as _os
    root, _queue = _fresh()
    bc, bs, bn, bo = _reload()
    runner = _Runner()
    rec = _Recorder()
    repo_root = Path(bo.__file__).resolve().parent.parent
    old = _os.getcwd()
    try:
        _os.chdir(str(repo_root / "scripts"))  # bewusst aus scripts/ (CWD-Falle)
        rc = bo.main(["--repo", "https://x/y"], run_fn=runner, send_fn=rec)
    finally:
        _os.chdir(old)
    # Die echten Repo-Seeds (01-*, 02-*) müssen gelaufen sein; README/.skip nicht.
    assert rc == 0, rc
    assert runner.calls, "main() ohne --queue fand keine Seeds (CWD-Falle?)"
    assert all(name.endswith(".md") and name.lower() != "readme.md"
               for name in runner.calls), runner.calls
    assert all(not name.endswith(".skip") for name in runner.calls), runner.calls
    print("  overnight OK — main() ohne --queue nutzt repo-relative Default-Queue")


def main() -> int:
    print("=== Overnight-Scheduler-Tests ===")
    tests = [
        test_empty_queue_does_nothing_but_reports,
        test_queue_order_and_skips,
        test_exit_code_mapping,
        test_failing_seed_does_not_abort_batch,
        test_dry_run_is_side_effect_free,
        test_state_record_written,
        test_digest_format_and_no_notify,
        test_config_guard_requires_repo,
        test_seed_timeout_counts_as_error,
        test_non_seed_files_excluded,
        test_default_queue_resolves_from_repo_root,
        test_main_without_queue_uses_default,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


# --- Mojibake-Regress (2026-06-06): mirror of job_poll — _real_run_fn must
#     decode loop_driver's UTF-8 output explicitly, else CP1252 on Windows.

class _FakeCompleted:
    def __init__(self, rc, out, err):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_real_run_fn_dekodiert_utf8():
    """_real_run_fn ruft subprocess.run mit encoding='utf-8' auf."""
    _fresh()
    _, _, _, bo = _reload()
    calls = {}

    def fake_run(cmd, **kw):
        calls["kw"] = kw
        return _FakeCompleted(0, "ok", "")

    orig = bo.subprocess.run
    bo.subprocess.run = fake_run
    try:
        bo._real_run_fn(seed_file=Path("x.md"), seed_text="## Ziel\nZ\n\n## Done-Kriterien\n- ok",
                        goal="Z", repo="https://x/y", max_rounds=1, round_timeout=30)
    finally:
        bo.subprocess.run = orig
    assert calls["kw"].get("encoding") == "utf-8", (
        "subprocess.run muss UTF-8 dekodieren — sonst CP1252-Mojibake auf Windows"
    )


if __name__ == "__main__":
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
