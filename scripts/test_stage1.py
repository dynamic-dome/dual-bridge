"""Stage 1 mechanics tests. Pure stdlib + assert, no pytest:
    python test_stage1.py

Isolated via DUAL_BRIDGE_ROOT -> tmp dir; a fake `codex` script stands in for
the real CLI. Proves mechanics ONLY -- contract fidelity against real codex
is verified in the live B roundtrip (spec section 6, L20).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-s1-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    return root


def test_parse_plain_text() -> None:
    import codex_adapter as ca
    assert ca.parse_codex_output("just a plain answer\n") == "just a plain answer"
    print("  parse OK -- plain text passes through")


def test_parse_strips_bom() -> None:
    import codex_adapter as ca
    assert ca.parse_codex_output("﻿hello") == "hello"
    print("  parse OK -- leading BOM stripped")


def test_parse_json_with_trailing_junk() -> None:
    import codex_adapter as ca
    # A JSON value followed by non-JSON hook noise (the L17 failure shape).
    raw = '{"answer": "fixed it"}\nPrompt stop hooks are not yet supported\n'
    out = ca.parse_codex_output(raw)
    assert "fixed it" in out, f"expected the answer text, got {out!r}"
    print("  parse OK -- JSON + trailing junk -> answer extracted")


def test_parse_empty_is_empty() -> None:
    import codex_adapter as ca
    assert ca.parse_codex_output("﻿   \n") == ""
    print("  parse OK -- whitespace/BOM-only -> empty string")


def _init_local_repo(tmp: Path) -> tuple[Path, Path]:
    """Create a bare 'remote' + a working clone, both in tmp. Returns
    (remote_path, work_parent). Uses git via subprocess; skips config prompts."""
    import subprocess
    remote = tmp / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                   capture_output=True)
    seed = tmp / "seed"
    subprocess.run(["git", "init", str(seed)], check=True, capture_output=True)
    for args in (
        ["git", "-C", str(seed), "config", "user.email", "t@t.t"],
        ["git", "-C", str(seed), "config", "user.name", "t"],
        ["git", "-C", str(seed), "checkout", "-b", "main"],
    ):
        subprocess.run(args, check=True, capture_output=True)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    for args in (
        ["git", "-C", str(seed), "add", "."],
        ["git", "-C", str(seed), "commit", "-m", "seed"],
        ["git", "-C", str(seed), "remote", "add", "origin", str(remote)],
        ["git", "-C", str(seed), "push", "origin", "main"],
    ):
        subprocess.run(args, check=True, capture_output=True)
    return remote, tmp / "work"


def test_git_clone_branch_commit_push() -> None:
    import codex_adapter as ca
    tmp = Path(tempfile.mkdtemp(prefix="git-s1-"))
    remote, work_parent = _init_local_repo(tmp)
    workdir = ca._git_clone_or_pull(str(remote), "main", work_parent / "t1")
    assert (workdir / "README.md").exists(), "clone did not bring README"
    ca._git_checkout_branch(workdir, "bridge/task-T1")
    (workdir / "new_file.txt").write_text("codex wrote this\n", encoding="utf-8")
    changed = ca._git_status_porcelain(workdir)
    assert "new_file.txt" in " ".join(changed), f"change not seen: {changed}"
    commit = ca._git_commit_and_push(workdir, "bridge/task-T1", "task T1")
    assert commit and len(commit) >= 7, f"no commit hash: {commit!r}"
    print("  git OK -- clone -> branch -> change -> commit -> push, hash returned")


def _write_fake_codex(tmp: Path, *, mode: str) -> Path:
    """Write a fake `codex` executable (python script + .cmd shim on Windows)
    that mimics the REAL `codex exec` interface (verified against codex-cli
    0.133): `codex exec [opts] <prompt>` with `-C <dir>`, `-s <sandbox>`, and
    `-o <FILE>` (final answer written to that file). The fake honours -o (writes
    the answer there) AND also prints to stdout, so both code paths are covered.
    mode controls behaviour:
      'write'  -> answer to -o/stdout AND creates a file in cwd (exit 0)
      'notext' -> creates a file but writes NO answer (empty -o/stdout, exit 0)
      'nofile' -> answer to -o/stdout, creates NO file (exit 0)
      'fail'   -> prints to stderr, exit 3
      'hang'   -> sleeps 30s (to trip a short timeout in the test)
    Returns the directory containing the fake codex.
    """
    bindir = tmp / "fakebin"
    bindir.mkdir(parents=True, exist_ok=True)
    py = bindir / "fake_codex.py"
    py.write_text(
        "import sys, os\n"
        f"mode = {mode!r}\n"
        "argv = sys.argv[1:]\n"
        "# Find -o/--output-last-message <FILE> and -C/--cd <DIR> like real codex.\n"
        "out_file = None\n"
        "cd_dir = None\n"
        "i = 0\n"
        "while i < len(argv):\n"
        "    a = argv[i]\n"
        "    if a in ('-o', '--output-last-message') and i + 1 < len(argv):\n"
        "        out_file = argv[i+1]; i += 2; continue\n"
        "    if a in ('-C', '--cd') and i + 1 < len(argv):\n"
        "        cd_dir = argv[i+1]; i += 2; continue\n"
        "    i += 1\n"
        "workdir = cd_dir or os.getcwd()\n"
        "# Record how the prompt arrived: stdin (real codex reads it when the\n"
        "# positional arg is '-') and the full argv. Lets a test prove the prompt\n"
        "# is piped, not passed as a cmd.exe-manglable arg (P008 / rule 10.8).\n"
        "stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ''\n"
        "import json as _json\n"
        "# Write the invocation record OUTSIDE workdir (in its parent), so it is\n"
        "# never seen by `git status` and cannot turn a no-file-change run into a\n"
        "# committed change (would break test_task_no_file_change_is_done).\n"
        "inv_path = os.path.join(os.path.dirname(workdir), '_codex_invocation.json')\n"
        "open(inv_path, 'w', encoding='utf-8')"
        ".write(_json.dumps({'argv': argv, 'stdin': stdin_text}))\n"
        "if mode == 'hang':\n"
        "    import time; time.sleep(30)\n"
        "if mode == 'fail':\n"
        "    sys.stderr.write('boom from fake codex\\n'); sys.exit(3)\n"
        "if mode in ('write', 'notext'):\n"
        "    open(os.path.join(workdir,'codex_made_this.txt'),'w',encoding='utf-8').write('hi\\n')\n"
        "answer = '' if mode == 'notext' else 'codex answer: done'\n"
        "if answer:\n"
        "    if out_file:\n"
        "        open(out_file,'w',encoding='utf-8').write(answer + '\\n')\n"
        "    sys.stdout.write(answer + '\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    # Windows shim so shutil.which('codex') resolves to a runnable .cmd.
    cmd = bindir / "codex.cmd"
    cmd.write_text(f'@echo off\r\npython "{py}" %*\r\n', encoding="utf-8")
    # POSIX shim (Laptop B is Windows, but keep tests portable).
    sh = bindir / "codex"
    sh.write_text(f'#!/bin/sh\nexec python "{py}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    return bindir


def _run_task(mode: str, *, timeout: int = 600):
    """Helper: fresh repo + fake codex of `mode`, call run_codex_task."""
    import codex_adapter as ca
    tmp = Path(tempfile.mkdtemp(prefix="task-s1-"))
    remote, work_parent = _init_local_repo(tmp)
    bindir = _write_fake_codex(tmp, mode=mode)
    codex_bin = str(bindir / ("codex.cmd" if os.name == "nt" else "codex"))
    return ca.run_codex_task(
        auftrag="do the thing", repo=str(remote), base_branch="main",
        task_id="T9", workroot=work_parent, codex_bin=codex_bin, timeout=timeout,
    )


def test_task_happy_path_writes_and_pushes() -> None:
    r = _run_task("write")
    assert r.status == "done", f"expected done, got {r.status}: {r.error_text}"
    assert r.branch == "bridge/task-T9"
    assert r.commit and len(r.commit) >= 7
    assert any("codex_made_this" in f for f in r.changed_files)
    assert "done" in r.antwort
    print("  task OK -- happy path: file written, branch pushed, answer captured")


def test_task_prompt_via_stdin_not_arg() -> None:
    """The (possibly long, special-char) prompt must reach codex via STDIN, not
    as a positional CLI arg — otherwise B's codex.CMD wrapper mangles/truncates
    it at the cmd.exe quoting layer (observed live 2026-05-31: codex saw the
    prompt only up to the first word; global rule 10.8 / P008, same fix the
    claude_adapter already carries). The positional arg must be '-' so real
    codex reads the instructions from stdin."""
    import json as _json
    long_prompt = (
        "## Auftrag\nImplementiere `secret_sweep_violation(x: dict) -> str | None` "
        "mit Mustern: sk-ant-..., -----BEGIN PRIVATE KEY-----, (klammern) | pipes.\n"
        * 3
    )
    tmp = Path(tempfile.mkdtemp(prefix="task-stdin-"))
    remote, work_parent = _init_local_repo(tmp)
    bindir = _write_fake_codex(tmp, mode="notext")  # writes invocation, no commit
    codex_bin = str(bindir / ("codex.cmd" if os.name == "nt" else "codex"))
    import codex_adapter as ca
    ca.run_codex_task(
        auftrag=long_prompt, repo=str(remote), base_branch="main",
        task_id="T9", workroot=work_parent, codex_bin=codex_bin,
    )
    inv_path = work_parent / "_codex_invocation.json"
    assert inv_path.exists(), "fake codex did not record its invocation"
    inv = _json.loads(inv_path.read_text(encoding="utf-8"))
    assert inv["stdin"] == long_prompt, "prompt did NOT arrive intact on stdin"
    assert long_prompt not in inv["argv"], "prompt must NOT be a positional arg"
    assert "-" in inv["argv"], "positional '-' (read-stdin) marker missing from argv"
    # The freshly cloned+branched workdir is a git repo by construction; codex
    # 0.135 otherwise refuses it as "not a trusted directory" (observed live B).
    assert "--skip-git-repo-check" in inv["argv"], "skip-git-repo-check flag missing"
    print("  task OK -- prompt piped via stdin, '-' arg, skip-git-repo-check set")


def test_task_codex_not_found() -> None:
    """Deterministic: point codex_bin at a guaranteed-absent path instead of
    relying on PATH. The old version fell back to shutil.which('codex') and, on
    a machine with codex installed, actually invoked the real CLI against the
    seed repo (slow, non-deterministic, real git/net) AND silently skipped the
    not-found assertion — masking the error path entirely (Codex review finding)."""
    import codex_adapter as ca
    tmp = Path(tempfile.mkdtemp(prefix="task-nf-"))
    remote, work_parent = _init_local_repo(tmp)
    missing = str(tmp / "no-such-codex-binary.exe")
    assert not Path(missing).exists()
    r = ca.run_codex_task("x", str(remote), "main", "T9", work_parent,
                          codex_bin=missing)
    assert r.status == "error" and r.error_text and "codex" in r.error_text.lower(), \
        f"expected codex-not-found error, got {r.status}/{r.error_text}"
    print("  task OK -- codex-not-found -> error (deterministic, no real codex)")


def test_task_repo_unreachable() -> None:
    import codex_adapter as ca
    tmp = Path(tempfile.mkdtemp(prefix="task-badrepo-"))
    bindir = _write_fake_codex(tmp, mode="write")
    codex_bin = str(bindir / ("codex.cmd" if os.name == "nt" else "codex"))
    r = ca.run_codex_task("x", repo=str(tmp / "does-not-exist.git"),
                          base_branch="main", task_id="T9",
                          workroot=tmp / "work", codex_bin=codex_bin)
    assert r.status == "error" and "clone" in (r.error_text or "").lower(), \
        f"expected clone error, got {r.status}/{r.error_text}"
    print("  task OK -- unreachable repo -> error before codex call")


def test_task_timeout() -> None:
    r = _run_task("hang", timeout=1)
    assert r.status == "error" and "timeout" in (r.error_text or "").lower(), \
        f"expected timeout error, got {r.status}/{r.error_text}"
    print("  task OK -- hanging codex -> timeout error")


def test_task_nonzero_exit() -> None:
    r = _run_task("fail")
    assert r.status == "error" and "exit" in (r.error_text or "").lower()
    assert "boom" in (r.stderr_excerpt or ""), "stderr not captured"
    print("  task OK -- exit 3 -> error with stderr excerpt")


def test_task_empty_output() -> None:
    r = _run_task("notext")
    assert r.status == "error" and "leer" in (r.error_text or "").lower()
    print("  task OK -- empty stdout -> error (exit 0 is not success)")


def test_task_no_file_change_is_done() -> None:
    r = _run_task("nofile")
    assert r.status == "done", f"no-change must be done, got {r.status}"
    assert r.branch is None and r.commit is None
    assert r.note and "keine" in r.note.lower()
    assert "done" in r.antwort
    print("  task OK -- codex answered but wrote no file -> done, text only")


def test_singleton_lock() -> None:
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    tmp = Path(tempfile.mkdtemp(prefix="lock-s1-"))
    lock = tmp / "poller.lock"

    # First acquire succeeds and writes our pid.
    assert bc.acquire_singleton_lock(lock) is True
    assert lock.exists()
    assert str(os.getpid()) in lock.read_text(encoding="utf-8")

    # The real protection: a DIFFERENT live process holds the lock -> refused.
    # getppid() is a foreign (!= ours), guaranteed-alive pid during the test.
    foreign_live = os.getppid()
    assert foreign_live != os.getpid()
    lock.write_text(f"{foreign_live}\n2026-01-01T00:00:00\n", encoding="utf-8")
    assert bc.acquire_singleton_lock(lock) is False, \
        "lock held by a foreign live process must refuse acquire"

    # Stale lock (dead pid) -> taken over.
    lock.write_text("999999999\n2026-01-01T00:00:00\n", encoding="utf-8")
    assert bc.acquire_singleton_lock(lock) is True, "stale lock must be taken over"

    # Release removes it (it is now ours again).
    bc.release_singleton_lock(lock)
    assert not lock.exists()
    print("  lock OK -- acquire/refuse-foreign-live/take-stale/release")


def test_poll_routes_implement_to_codex() -> None:
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    _fresh_bridge()
    bc.ensure_dirs()
    import handoff_poll as hp
    importlib.reload(hp)

    import codex_adapter as ca
    tmp = Path(tempfile.mkdtemp(prefix="poll-impl-"))
    remote, work_parent = _init_local_repo(tmp)
    bindir = _write_fake_codex(tmp, mode="write")
    codex_bin = str(bindir / ("codex.cmd" if os.name == "nt" else "codex"))

    # Point the poller's codex workroot at our temp; the codex runner reads the
    # bin/timeout from the environment (DUAL_BRIDGE_CODEX_BIN/_TIMEOUT).
    hp.CODEX_WORKROOT = work_parent
    os.environ["DUAL_BRIDGE_CODEX_BIN"] = codex_bin
    os.environ["DUAL_BRIDGE_CODEX_TIMEOUT"] = "600"

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "implement", "adapter": "codex",
        "repo": str(remote), "base_branch": "main",
        "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nbau das feature\n"))

    try:
        assert hp.process_one(task, lane=bc.DEFAULT_LANE) is True
    finally:
        del os.environ["DUAL_BRIDGE_CODEX_BIN"]
        del os.environ["DUAL_BRIDGE_CODEX_TIMEOUT"]
    result = bc.inbox_dir() / f"result-{task_id}.md"
    rfm, rbody = bc.parse_frontmatter(bc.read_text_utf8(result))
    assert rfm["status"] == "done", f"expected done, got {rfm.get('status')}"
    assert rfm["kind"] == "implement"
    assert rfm.get("branch") == f"bridge/task-{task_id}"
    assert rfm.get("commit"), "no commit hash in result frontmatter"
    assert "codex answer" in rbody
    print("  poll OK -- implement task routed to codex, result has branch+commit")


def test_poll_echo_still_works() -> None:
    """Regression: kind:echo must still produce the Stage-0 echo, no codex."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    _fresh_bridge()
    bc.ensure_dirs()
    import handoff_poll as hp
    importlib.reload(hp)

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "echo", "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nspiegel mich\n"))
    assert hp.process_one(task, lane=bc.DEFAULT_LANE) is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.inbox_dir() / f"result-{task_id}.md"))
    assert rfm["status"] == "done"
    assert "spiegel mich" in rbody and "Echo" in rbody, "echo path changed -- regression!"
    assert "branch" not in rfm, "echo result must not carry a branch"
    print("  poll OK -- echo regression intact, no codex, no branch")


def test_write_includes_repo_fields() -> None:
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    _fresh_bridge()
    import handoff_write as hw
    importlib.reload(hw)

    rc = hw.main(["bau das feature", "--kind", "implement",
                  "--repo", "https://example.test/repo.git",
                  "--base-branch", "main"])
    assert rc == 0
    tasks = list(bc.outbox_dir().glob("task-*.md"))
    assert len(tasks) == 1
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(tasks[0]))
    assert fm["kind"] == "implement"
    assert fm["repo"] == "https://example.test/repo.git"
    assert fm["base_branch"] == "main"
    print("  write OK -- implement task carries repo + base_branch")


def test_collect_shows_pull_hint() -> None:
    import importlib, io, contextlib
    import bridge_common as bc
    importlib.reload(bc)
    _fresh_bridge()
    bc.ensure_dirs()
    import handoff_collect as hc
    importlib.reload(hc)

    fm = {"created": bc.now_iso(), "agent": "laptop-b", "status": "done",
          "task_id": "T7", "kind": "implement", "branch": "bridge/task-T7",
          "commit": "deadbee"}
    bc.write_text_utf8(bc.inbox_dir() / "result-T7.md",
                       bc.build_document(fm, "## Codex-Antwort\nok\n"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        hc.collect_once(peek=True)
    out = buf.getvalue()
    assert "bridge/task-T7" in out and "git checkout" in out, \
        f"pull hint missing in collector output:\n{out}"
    print("  collect OK -- done result shows git checkout hint")


def main() -> int:
    _fresh_bridge()
    print("=== Stage-1-Tests (codex adapter + poller routing + lock) ===")
    tests = [
        test_parse_plain_text, test_parse_strips_bom,
        test_parse_json_with_trailing_junk, test_parse_empty_is_empty,
        test_git_clone_branch_commit_push,
        test_task_happy_path_writes_and_pushes, test_task_codex_not_found,
        test_task_repo_unreachable, test_task_timeout, test_task_nonzero_exit,
        test_task_empty_output, test_task_no_file_change_is_done,
        test_singleton_lock,
        test_poll_routes_implement_to_codex, test_poll_echo_still_works,
        test_write_includes_repo_fields, test_collect_shows_pull_hint,
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
