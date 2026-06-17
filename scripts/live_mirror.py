#!/usr/bin/env python3
"""Live-mirror a single real-git regression test against its REAL live path.

Seed 07 (docs/overnight/07-test-live-mirror.md), stage 1 of the maturity path
born from the crazy-professor "Test grün ≠ Live korrekt" provocation (P012).

The mirrored unit test is `test_codex_self_commit_is_seen_as_progress` in
`test_loop_continuity_realgit.py`. It covers exactly the class of one of the
three live-only loop bugs (`_commits_ahead_of_base`): codex-cli 0.136 under
`-s danger-full-access` self-commits, so the working tree is clean afterwards
but HEAD is one commit ahead of origin/base. The adapter MUST surface that as a
real commit + non-empty diff (and push it), not drop it as "no change".

WHY this is a genuine mirror, not a copy of the test
----------------------------------------------------
The unit test monkeypatches `codex_adapter.subprocess.run` away entirely, so the
real `subprocess.run` call — argv assembly, stdin prompt, the codex.CMD quoting
layer, the actual process spawn, the `-o` answer-file round-trip — is NEVER
exercised. This script instead writes a REAL executable fake-codex binary to
disk and feeds it through `run_codex_task(codex_bin=...)`, so the genuine
`subprocess.run` path runs against a genuine binary. The only thing still faked
is what codex *produces* (a deterministic file change + self-commit) — which is
the one thing we cannot afford to run a real LLM for in a 1-hour prototype.

So the live path here is STRICTLY CLOSER to production than the unit test: it
adds back the whole subprocess/argv/stdin layer the test stubs out, while
keeping the same git setup. If the unit-test assertion holds but the live path
diverges, that divergence is the bug class the test could not see — which is the
entire point of the seed (a red result is success, not failure).

Isolation (global CLAUDE.md rule 3)
-----------------------------------
Everything runs inside a single `tempfile.mkdtemp()` throwaway tree: a local
bare "origin" repo (no network, no real remote) plus a work clone. No production
DB, no real repo, no Google-Drive bridge root is ever touched. The temp tree is
removed on exit.

Exit codes
----------
0  live path matches the mirrored unit-test assertion (maturity-path stage 1
   proven for this test → seed 08 may be unlocked)
1  divergence: live path disagrees with the unit-test assertion (a real gap the
   test did not see — valuable, see seed "Erwartung / Akzeptanz")
2  harness error (could not even set up the mirror — neither pass nor fail)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

# run_codex_task lives in codex_adapter; import the module the same way the
# tests do (scripts/ on sys.path when run from there).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_adapter as ca  # noqa: E402

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


# --- git helper (identical shape to the mirrored test) ----------------------
def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
    )


def _make_origin(tmp: Path) -> str:
    """Create a bare origin repo with one commit on main, return its path.

    Byte-for-byte the same setup as the mirrored unit test's `_make_origin`."""
    seed = tmp / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(seed)], check=True,
                   capture_output=True, creationflags=_NO_WINDOW)
    _git(seed, "config", "user.email", "t@t.local")
    _git(seed, "config", "user.name", "t")
    (seed / "f.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "base")
    bare = tmp / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(seed), str(bare)],
                   check=True, capture_output=True, creationflags=_NO_WINDOW)
    return str(bare)


# --- the real fake-codex binary ---------------------------------------------
# A genuine on-disk executable that mimics codex-cli 0.136 under
# danger-full-access: append a line to f.txt in the -C workdir, self-commit it,
# and write the final agent message to the -o answer file. Spawned by the REAL
# subprocess.run inside run_codex_task — this is the layer the unit test stubs.
_FAKE_CODEX_SRC = textwrap.dedent(
    '''\
    #!/usr/bin/env python3
    """Deterministic fake of `codex exec` for the live-mirror prototype.

    Parses the same argv run_codex_task builds (-C workdir, -o answerfile, ...),
    appends MIRROR_LINE to f.txt in the workdir, self-commits (like codex 0.136
    under danger-full-access), and writes the answer file. The prompt arrives on
    stdin (which we read and ignore, exactly as the real binary tolerates)."""
    import subprocess
    import sys
    from pathlib import Path

    MIRROR_LINE = "self-committed-line"

    def main() -> int:
        argv = sys.argv[1:]
        try:
            sys.stdin.read()  # drain the prompt; the fake does not need it
        except Exception:
            pass
        workdir = None
        answer_file = None
        for i, tok in enumerate(argv):
            if tok == "-C" and i + 1 < len(argv):
                workdir = Path(argv[i + 1])
            elif tok == "-o" and i + 1 < len(argv):
                answer_file = Path(argv[i + 1])
        if workdir is None:
            sys.stderr.write("fake-codex: no -C workdir in argv\\n")
            return 3
        f = workdir / "f.txt"
        f.write_text(
            f.read_text(encoding="utf-8") + MIRROR_LINE + "\\n",
            encoding="utf-8",
        )
        # codex 0.136 self-commits → working tree clean afterwards.
        def g(*a):
            return subprocess.run(["git", "-C", str(workdir), *a],
                                  capture_output=True, text=True)
        g("add", "-A")
        g("commit", "-m", "codex self-commit")
        if answer_file is not None:
            answer_file.write_text("done", encoding="utf-8")
        sys.stdout.write("ok")
        return 0

    if __name__ == "__main__":
        sys.exit(main())
    '''
)

MIRROR_LINE = "self-committed-line"


def _write_fake_codex(tmp: Path) -> str:
    """Write a real, executable fake-codex and return a path run_codex_task can
    spawn. On Windows a bare `.py` is not directly spawnable by subprocess, so we
    emit a `.cmd` shim that calls the current interpreter on the `.py` — and the
    shim is named `codex.cmd` so the adapter's `exe.endswith('codex'/'codex.exe')`
    discrimination (and any future name check) sees a codex binary."""
    py = tmp / "fake_codex.py"
    py.write_text(_FAKE_CODEX_SRC, encoding="utf-8")
    if sys.platform == "win32":
        shim = tmp / "codex.cmd"
        # %* forwards all args; prompt on stdin is inherited through the shim.
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{py}" %*\r\n',
            encoding="utf-8",
        )
        return str(shim)
    # POSIX: make the .py itself executable and return it (named so it ends in
    # 'codex' for the adapter's binary check).
    posix = tmp / "codex"
    posix.write_text(_FAKE_CODEX_SRC, encoding="utf-8")
    posix.chmod(0o755)
    return str(posix)


# --- the mirror --------------------------------------------------------------
def run_mirror(verbose: bool = False) -> tuple[int, str]:
    """Run the live mirror in an isolated temp tree. Returns (exit_code, line).

    `line` is the one-sentence proof string written to docs/live-proofs/."""
    if shutil.which("git") is None:
        return 2, "Harness-Fehler: git nicht im PATH gefunden."

    tmp = Path(tempfile.mkdtemp(prefix="live-mirror-"))
    try:
        origin = _make_origin(tmp)
        workroot = tmp / "work"
        fake_codex = _write_fake_codex(tmp)

        # THE REAL LIVE PATH: same call the build-review loop makes, against a
        # genuine binary via the genuine subprocess.run (codex_bin injected so
        # nothing is monkeypatched).
        r = ca.run_codex_task(
            auftrag="build", repo=origin, base_branch="main",
            task_id="sc1", workroot=workroot,
            branch="bridge/loop-SC", workdir_name="loop-SC",
            codex_bin=fake_codex,
        )

        # The mirrored unit test asserts, on the SAME setup:
        #   r.status == "done"
        #   r.commit is truthy            (self-commit seen as progress, Bug 2)
        #   r.diff contains MIRROR_LINE   (non-empty review diff, Bug 3)
        #   the self-commit was pushed to origin/<branch> (continuity, MAJOR)
        # We evaluate each live-side and compare to the expected (unit) verdict.
        checks: list[tuple[str, object, object]] = []
        checks.append(("status == done", "done", r.status))
        checks.append(("commit truthy", True, bool(r.commit)))
        checks.append((
            "diff contains self-committed-line",
            True,
            bool(r.diff) and MIRROR_LINE in (r.diff or ""),
        ))

        # Push/continuity check: clone the pushed branch from origin and confirm
        # the tip carries the self-committed line (exactly the unit test's
        # stronger assertion).
        pushed_ok = False
        probe = tmp / "probe"
        clone = subprocess.run(
            ["git", "clone", "--branch", "bridge/loop-SC", origin, str(probe)],
            capture_output=True, text=True, creationflags=_NO_WINDOW,
        )
        if clone.returncode == 0 and (probe / "f.txt").exists():
            pushed_ok = MIRROR_LINE in (probe / "f.txt").read_text(encoding="utf-8")
        checks.append(("self-commit pushed to origin/branch", True, pushed_ok))

        divergences = [(name, exp, got) for name, exp, got in checks if exp != got]

        if verbose:
            print(f"  live status     : {r.status!r}")
            print(f"  live commit     : {r.commit!r}")
            print(f"  live diff len   : {len(r.diff or '')} chars")
            print(f"  live error_text : {r.error_text!r}")
            print(f"  pushed_ok       : {pushed_ok}")
            for name, exp, got in checks:
                mark = "OK " if exp == got else "!! "
                print(f"  [{mark}] {name}: expected {exp!r}, live {got!r}")

        if not divergences:
            line = (
                "Unit-Test `test_codex_self_commit_is_seen_as_progress` und der "
                "Live-Pfad (`run_codex_task` mit echtem subprocess + echter "
                "Fake-codex-Binary, echtes lokales git) stimmen überein: "
                "self-commit wird als Fortschritt erkannt (commit gesetzt, Diff "
                f"trägt `{MIRROR_LINE}`, push nach origin/bridge/loop-SC bestätigt)."
            )
            return 0, line

        diff_txt = "; ".join(
            f"{name}: erwartet {exp!r}, live {got!r}" for name, exp, got in divergences
        )
        if r.error_text:
            diff_txt += f" | live error_text={r.error_text!r}"
        line = (
            "Divergenz gefunden zwischen Unit-Test "
            "`test_codex_self_commit_is_seen_as_progress` und Live-Pfad "
            f"(`run_codex_task`): {diff_txt}."
        )
        return 1, line
    except Exception as exc:  # harness error — neither a pass nor a real fail
        return 2, f"Harness-Fehler beim Live-Mirror-Setup: {exc!r}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _proof_path() -> Path:
    """docs/live-proofs/, resolved repo-relative (rule: never CWD-relative)."""
    return Path(__file__).resolve().parent.parent / "docs" / "live-proofs"


def _write_proof(exit_code: int, line: str) -> Path:
    proofs = _proof_path()
    proofs.mkdir(parents=True, exist_ok=True)
    target = proofs / "07-test-live-mirror.md"
    status = {0: "ÜBEREINSTIMMUNG", 1: "DIVERGENZ", 2: "HARNESS-FEHLER"}[exit_code]
    # Timestamp is intentionally NOT embedded (deterministic content); git log
    # carries the when. Overwrite so the file always reflects the latest run.
    body = textwrap.dedent(
        f"""\
        # Live-Proof — Seed 07 (test-live-mirror)

        **Ergebnis:** {status} (exit {exit_code})

        {line}

        ## Was gespiegelt wurde
        Unit-Test `test_codex_self_commit_is_seen_as_progress`
        (`scripts/test_loop_continuity_realgit.py`) gegen den echten
        `run_codex_task`-Live-Pfad — gefahren von `scripts/live_mirror.py` in
        einem isolierten `tempfile`-Klon (lokales bare origin, kein Netzwerk,
        keine Production-DB, kein Drive-Bridge-Root; CLAUDE.md §3).

        Anders als der Unit-Test (der `subprocess.run` wegmonkeypatcht) fährt der
        Live-Pfad die echte `subprocess.run`-Schicht gegen eine echte
        Fake-codex-Binary — also strikt näher an Produktion. Eine Divergenz wäre
        genau die live-only-Bug-Klasse, die der Test nicht sieht (P012).
        """
    )
    target.write_text(body, encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="print each live-vs-expected check")
    p.add_argument("--no-proof", action="store_true",
                   help="do not write docs/live-proofs/ (CI / dry-run)")
    args = p.parse_args(argv)

    exit_code, line = run_mirror(verbose=args.verbose)
    print(line)
    if not args.no_proof:
        target = _write_proof(exit_code, line)
        print(f"→ Proof: {target}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
