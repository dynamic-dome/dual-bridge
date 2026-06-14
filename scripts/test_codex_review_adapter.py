"""run_codex_review tests against a fake codex CLI (unit level; the real-binary
proof lives in the Stage-A live-proof, not here).

Mirrors test_claude_adapter.py: the codex review adapter is the codex-side
review-only runner (capability=read), symmetric to the `claude` reviewer. It
returns TEXT only (a verdict), never a git branch, and must survive the codex
read-only sandbox without the approval-probing hang (CLAUDE.md rule 10.10).
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def _write_fake_codex(tmp: Path, *, answer: str, exit_code: int = 0) -> str:
    """A fake codex that prints `answer` to stdout and exits `exit_code`."""
    bindir = tmp / "fakebin"; bindir.mkdir(parents=True, exist_ok=True)
    py = bindir / "fake_codex.py"
    py.write_text(
        "import sys\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        f"ans = {answer!r}\n"
        f"code = {exit_code}\n"
        "if ans:\n"
        "    sys.stdout.write(ans + '\\n')\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    cmd = bindir / "codex.cmd"
    cmd.write_text(f'@echo off\r\npython "{py}" %*\r\n', encoding="utf-8")
    sh = bindir / "codex"
    sh.write_text(f'#!/bin/sh\nexec python "{py}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    return str(bindir / ("codex.cmd" if os.name == "nt" else "codex"))


def _write_argdump_codex(tmp: Path) -> tuple[str, Path, Path]:
    """A fake codex dumping argv + stdin to files, then a valid verdict. Lets us
    assert which flags the adapter passes and that the prompt arrives via stdin
    (not a CLI arg the cmd.exe wrapper would mangle, P008/rule 10.8)."""
    bindir = tmp / "fakebin"; bindir.mkdir(parents=True, exist_ok=True)
    argfile = tmp / "argv.txt"
    stdinfile = tmp / "stdin.txt"
    py = bindir / "fake_codex.py"
    py.write_text(
        "import sys\n"
        "try:\n"
        "    sys.stdout.reconfigure(encoding='utf-8')\n"
        "    sys.stdin.reconfigure(encoding='utf-8')\n"
        "except Exception:\n"
        "    pass\n"
        f"open(r{str(argfile)!r}, 'w', encoding='utf-8').write('\\n'.join(sys.argv[1:]))\n"
        f"open(r{str(stdinfile)!r}, 'w', encoding='utf-8').write(sys.stdin.read())\n"
        "sys.stdout.write('VERDICT: accepted\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    cmd = bindir / "codex.cmd"
    cmd.write_text(f'@echo off\r\npython "{py}" %*\r\n', encoding="utf-8")
    sh = bindir / "codex"
    sh.write_text(f'#!/bin/sh\nexec python "{py}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    return str(bindir / ("codex.cmd" if os.name == "nt" else "codex")), argfile, stdinfile


def test_run_codex_review_happy() -> None:
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-"))
    fake = _write_fake_codex(tmp, answer="sieht gut aus\nVERDICT: accepted")
    r = cra.run_codex_review(auftrag="review diff", fm={"task_id": "T1"},
                             workroot=tmp, codex_bin=fake)
    assert r.status == "done", f"got {r.status}: {r.error_text}"
    assert "VERDICT: accepted" in r.antwort
    assert r.branch is None, "der Reviewer darf KEINEN git-branch erzeugen"


def test_run_codex_review_not_found() -> None:
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-nf-"))
    missing = str(tmp / "no-such-codex.exe")
    r = cra.run_codex_review("x", {"task_id": "T1"}, tmp, codex_bin=missing)
    assert r.status == "error" and "codex" in (r.error_text or "").lower()


def test_run_codex_review_nonzero_exit_with_answer_is_done() -> None:
    """P007: a parseable verdict despite a nonzero exit is real — exit lies."""
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-x1-"))
    fake = _write_fake_codex(tmp, answer="VERDICT: rejected\nfehlt Test", exit_code=1)
    r = cra.run_codex_review("review", {"task_id": "T1"}, tmp, codex_bin=fake)
    assert r.status == "done", f"expected done despite exit 1, got {r.status}"
    assert "VERDICT: rejected" in r.antwort


def test_run_codex_review_empty_answer_is_error() -> None:
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-e-"))
    fake = _write_fake_codex(tmp, answer="", exit_code=1)
    r = cra.run_codex_review("review", {"task_id": "T1"}, tmp, codex_bin=fake)
    assert r.status == "error"


def test_run_codex_review_read_only_and_no_approval_probing() -> None:
    """The hang-proofing (rule 10.10): a read-only review must NOT trigger codex's
    approval-probing shell loop. The adapter passes -s read-only +
    approval_policy=never + --skip-git-repo-check so a no-write review returns
    immediately instead of probing for a writable dir."""
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-flags-"))
    fake, argfile, _ = _write_argdump_codex(tmp)
    r = cra.run_codex_review("review", {"task_id": "T1"}, tmp, codex_bin=fake)
    assert r.status == "done", f"got {r.status}: {r.error_text}"
    argv = argfile.read_text(encoding="utf-8").splitlines()
    assert "exec" in argv
    assert "-s" in argv and argv[argv.index("-s") + 1] == "read-only", argv
    joined = "\n".join(argv)
    assert 'approval_policy="never"' in joined, argv
    assert "--skip-git-repo-check" in argv, argv


def test_run_codex_review_prompt_via_stdin_not_argv() -> None:
    import codex_review_adapter as cra
    importlib.reload(cra)
    tmp = Path(tempfile.mkdtemp(prefix="codexrev-stdin-"))
    fake, argfile, stdinfile = _write_argdump_codex(tmp)
    tricky = ("Review diff with `git push` (no). End with `VERDICT: accepted`\n"
              "or `VERDICT: rejected`.")
    r = cra.run_codex_review(tricky, {"task_id": "T1"}, tmp, codex_bin=fake)
    assert r.status == "done", f"got {r.status}: {r.error_text}"
    assert tricky in stdinfile.read_text(encoding="utf-8")
    assert tricky not in argfile.read_text(encoding="utf-8").splitlines()


def main() -> int:
    tests = [test_run_codex_review_happy, test_run_codex_review_not_found,
             test_run_codex_review_nonzero_exit_with_answer_is_done,
             test_run_codex_review_empty_answer_is_error,
             test_run_codex_review_read_only_and_no_approval_probing,
             test_run_codex_review_prompt_via_stdin_not_argv]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
