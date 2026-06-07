"""Codex worker adapter for the Dual-Laptop-Bridge (Stage 1).

Owns the real `codex exec` call plus the git clone/branch/commit/push dance.
Knows NOTHING about the bridge (no frontmatter, no Sharepoint paths) -- it takes
a task text + repo and returns a CodexResult. Pure stdlib.

Output parsing follows the L17/P006 lesson (BOM + event-stream + hook noise):
strip a BOM, raw_decode the first JSON value if present, else treat as plain
text. The exact real codex-exec format is verified in the live B run (L20).

codex exec flags (verified against codex-cli 0.133, `codex exec --help`):
  -C <dir>            explicit working root
  -s workspace-write  sandbox that may write inside the workspace
  -o <FILE>           final agent message written to that file (robust; avoids
                      the stdout BOM/event-stream/hook-noise problem entirely)
"""
from __future__ import annotations

import json
import sys

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_codex_output(raw: str) -> str:
    """Extract the answer text from codex output, tolerant of BOM, a JSON value
    with trailing non-JSON noise, or plain text. Returns "" if empty."""
    if raw is None:
        return ""
    text = raw.lstrip("﻿").strip()
    if not text:
        return ""
    # NDJSON path (codex exec --json emits one JSON event per line). Parse each
    # non-empty line with raw_decode (BOM-tolerant) and collect what decodes.
    # ONLY treat the stream as NDJSON when >1 event actually decodes -- a single,
    # possibly pretty-printed JSON object that merely contains "\n" must NOT be
    # misread as NDJSON, so it falls through to the single raw_decode path below.
    if text[0] in "{[" and "\n" in text:
        events = []
        ndjson = True
        for line in text.splitlines():
            line = line.lstrip("﻿").strip()
            if not line:
                continue
            if line[0] not in "{[":
                continue  # trailing hook noise -> not an event, ignore
            try:
                value, end = json.JSONDecoder().raw_decode(line)
            except ValueError:
                continue  # undecodable line -> skip, do not abort the stream
            # A genuine NDJSON line is a COMPLETE JSON value: raw_decode must
            # consume essentially the whole line. If a line is only the partial
            # start of a value (e.g. "[" or "{" of a pretty-printed array/object
            # spanning lines), this is NOT NDJSON -> fall through to single path.
            if end < len(line.rstrip().rstrip(",")):
                ndjson = False
                break
            events.append(value)
        if ndjson and len(events) > 1:
            # Q3b: pick the last event that carries a REAL answer key. A trailing
            # metadata event (turn.completed/usage) has no answer -> must not be
            # stringified and returned as if it were the answer.
            for value in reversed(events):
                ans = _strict_answer_from_event(value)
                if ans:
                    return ans
            return ""
    # Single JSON value (event-stream array or single object); ignore trailing junk.
    if text[0] in "{[":
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            value = None
        if value is not None:
            return _answer_from_json(value).strip()
    return text


# Known NON-answer NDJSON event 'type' values (status / lifecycle / usage /
# error). We use a DENYLIST, not an allowlist (Codex-Verifier Q3b round 3): a
# closed answer-type allowlist would silently DROP a real answer carried by an
# event type we did not foresee (e.g. message.output_text.delta). Denylisting
# the known metadata types instead means an UNKNOWN type is still mined for an
# answer key -- fail toward preserving the answer, not losing it. Substring
# match catches the whole families (turn.*, thread.*, *.failed, error.*).
_NON_ANSWER_TYPE_SUBSTR = (
    "thread.started", "thread.", "turn.started", "turn.completed", "turn.failed",
    "turn.", "usage", "error", ".failed", ".aborted", ".cancelled", "rate_limit",
    "tool_call", "reasoning",
)


def _is_non_answer_type(etype: str) -> bool:
    low = etype.lower()
    return any(s in low for s in _NON_ANSWER_TYPE_SUBSTR)


def _strict_answer_from_event(value: object) -> str:
    """Answer text from ONE NDJSON event, or "" if it carries none.

    Unlike _answer_from_json this never falls back to json.dumps(value): a
    metadata-only event (turn.completed/usage/thread.started) must yield "" so
    the NDJSON selector skips it instead of mistaking its serialisation for the
    answer (Codex-Verifier Q3b).

    A declared metadata 'type' (denylisted family above) yields "" so a trailing
    status/error event cannot shadow the real answer. ANY other type -- known or
    not -- is mined for an answer key, so an unforeseen answer-bearing type is
    never silently dropped."""
    if not isinstance(value, dict):
        return ""
    etype = value.get("type")
    if isinstance(etype, str) and _is_non_answer_type(etype):
        return ""  # declared metadata/status/error event -> skip
    for key in ("answer", "result", "message", "text", "content", "output"):
        v = value.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for key in ("item", "agent_message"):
        sub = value.get(key)
        if isinstance(sub, dict):
            for k in ("text", "result", "message", "content"):
                v = sub.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        elif isinstance(sub, str) and sub.strip():
            return sub.strip()
    return ""


def _answer_from_json(value: object) -> str:
    """Pull a human answer out of a decoded JSON value. Tolerant of shapes we
    cannot yet pin down (verified against real codex in the B run): try common
    keys, then a final 'result'/'message' event in a list, else stringify."""
    if isinstance(value, dict):
        for key in ("answer", "result", "message", "text", "content", "output"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        # NDJSON event shapes: codex item.completed wraps the answer in an
        # "item" sub-dict; an agent_message event carries it directly. Look one
        # level deeper before stringifying so the real answer is not lost.
        for key in ("item", "agent_message"):
            sub = value.get(key)
            if isinstance(sub, dict):
                for k in ("text", "result", "message", "content"):
                    v = sub.get(k)
                    if isinstance(v, str) and v.strip():
                        return v
            elif isinstance(sub, str) and sub.strip():
                return sub
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict):
                for key in ("result", "message", "text", "content"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


import os
import shutil
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from bridge_common import config_value, safe_subprocess_env
from runners import RunnerResult, register_runner

CodexResult = RunnerResult  # back-compat alias; existing call sites unchanged


def _run_git(workdir: Path | None, *args: str,
             cred: "_Cred | None" = None) -> subprocess.CompletedProcess:
    """Run a git command, capturing output as utf-8. cwd=workdir if given.

    cred (if given) overlays GIT_ASKPASS + GIT_BRIDGE_CREDFILE onto the hardened
    child env so git answers its own credential prompt from an ephemeral store
    file -- see _resolve_https_credential for why the hardened subprocess env
    cannot rely on GCM resolving the token itself, and why we use ASKPASS+file
    rather than an env-var token or an inline shell helper."""
    cmd = ["git"]
    if workdir is not None:
        cmd += ["-C", str(workdir)]
    cmd += list(args)
    env = safe_subprocess_env(cred.env if cred else None)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        stdin=subprocess.DEVNULL, env=env,
    )


@dataclass
class _Cred:
    """Ephemeral credential carrier for a single _git_clone_or_pull invocation.

    `env` is the GIT_ASKPASS + GIT_BRIDGE_CREDFILE overlay for the child git env.
    `store_path` (if set) is a temp file holding the token; `wrapper_path` is the
    generated askpass wrapper. BOTH MUST be deleted after the git calls (see
    _git_clone_or_pull's finally). An empty _Cred (env={}) means "no helper" --
    local/ssh remotes or unresolved creds."""
    env: dict
    store_path: Path | None = None
    wrapper_path: Path | None = None

    def cleanup(self) -> None:
        """Delete the token-bearing store file and the askpass wrapper."""
        for p in (self.store_path, self.wrapper_path):
            if p is not None:
                try:
                    p.unlink()
                except OSError:
                    pass


# Resolved once: the GIT_ASKPASS helper sits next to this module.
_ASKPASS_HELPER = (Path(__file__).resolve().parent / "git_askpass_helper.py")


def _resolve_https_credential(repo: str) -> _Cred:
    """Resolve an HTTPS remote's credentials in the PARENT and feed them to the
    child git via GIT_ASKPASS pointing at an ephemeral store file (NOT an env-var
    token, NOT an inline shell helper, NOT a `store --file=` config).

    Why this exists: clone/fetch run under safe_subprocess_env() (allowlist-only,
    secret-free by design). On a host where the real credential is in the Windows
    Credential Manager (GCM), the hardened child can fail to unlock it -- git then
    silently falls back to ANONYMOUS access. Against a PRIVATE repo that anonymous
    request returns an empty ref list, so `git clone --branch main` dies with the
    misleading 'Remote branch main not found in upstream origin' (observed
    2026-06-06, every queued goal-loop -> rc=3). We sidestep that by resolving the
    token here (the parent's env still reaches GCM normally) and handing it to the
    child for exactly this one clone.

    Why GIT_ASKPASS + a store file (and NOT the alternatives):
      - env-var token: safe_subprocess_env's denylist kills GIT_PASSWORD/_TOKEN by
        name, and putting the secret in the environment is exactly what the
        hardening forbids.
      - inline `!sh` helper: puts the token on git's COMMAND LINE (ps/tasklist
        leak) AND interpolates user/pw into a shell string -- a `'` in the
        password becomes shell injection.
      - `credential.helper=store --file=<win-path>`: that helper runs via sh
        (git-bash); a Windows path in --file= is unreadable there, so git falls
        back to an interactive /dev/tty prompt and dies 'could not read Username'
        (global rule §10.3).
    GIT_ASKPASS is exec'd directly by git (no shell), reads the token from a file
    whose PATH (not the token) travels in an env var, and is Windows-path-safe.
    The token never touches argv, env, or a shell. The file is chmod 600 and
    deleted by the caller's finally.

    Returns an empty _Cred for non-HTTPS remotes (local/file/ssh paths -- e.g. the
    real-git test origins -- authenticate without a helper) or when no credential
    resolves (let git try its own helpers and surface the real error)."""
    if not repo.lower().startswith("https://"):
        return _Cred(env={})
    fill = subprocess.run(
        ["git", "credential", "fill"],
        input=f"url={repo}\n\n", capture_output=True, text=True,
        encoding="utf-8", env=safe_subprocess_env(),
    )
    if fill.returncode != 0:
        return _Cred(env={})
    creds = {}
    for line in fill.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            creds[k.strip()] = v.strip()
    user, pw = creds.get("username"), creds.get("password")
    protocol = creds.get("protocol", "https")
    host = creds.get("host")
    if not user or not pw or not host:
        return _Cred(env={})
    # Store line in git's credential-store format. URL-encode user/pw so ':' '@'
    # '/' or any special char cannot corrupt the line or smuggle a second entry;
    # the askpass helper urldecodes them back. Same encoding git itself uses.
    enc = lambda s: urllib.parse.quote(s, safe="")
    line = f"{protocol}://{enc(user)}:{enc(pw)}@{host}\n"
    # mkstemp creates the file with 0600 already (owner-only) and in the user's
    # private TEMP. The store + the GIT_BRIDGE_CREDFILE pointer are an ACCEPTED
    # residual risk: a process that can read this worker's env/TEMP runs as the
    # same user and could read GCM / the token directly anyway. The file lives
    # only for the duration of the git calls and is deleted in the caller's
    # finally, so the window is sub-second.
    fd, name = tempfile.mkstemp(prefix="bridge-cred-", suffix=".store")
    store_path = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(line)
        os.chmod(store_path, 0o600)  # best-effort; on Windows NTFS ACLs differ
    except Exception:
        try:
            store_path.unlink()
        except OSError:
            pass
        return _Cred(env={})
    # GIT_ASKPASS must be a single executable git can exec with one arg (the
    # prompt) -- it cannot be "python script.py" (two tokens). We generate a tiny
    # per-call wrapper (a .cmd on Windows, an sh shebang script elsewhere) that
    # invokes THIS interpreter on the helper script. The wrapper carries no
    # secret, only the (fixed) interpreter + helper paths. GIT_BRIDGE_CREDFILE
    # (a path, GIT_-prefixed so it survives the allowlist) tells the helper which
    # store file to read. GIT_TERMINAL_PROMPT=0 stops any interactive fallback.
    # If wrapper generation fails, the store file must not leak (it holds the
    # token). Clean it up before propagating an empty _Cred.
    try:
        wrapper_path = _write_askpass_wrapper()
    except OSError:
        try:
            store_path.unlink()
        except OSError:
            pass
        return _Cred(env={})
    env = {
        "GIT_ASKPASS": str(wrapper_path),
        "GIT_BRIDGE_CREDFILE": store_path.as_posix(),
        "GIT_TERMINAL_PROMPT": "0",
    }
    return _Cred(env=env, store_path=store_path, wrapper_path=wrapper_path)


def _write_askpass_wrapper() -> Path:
    """Generate a one-call executable wrapper that runs the askpass helper with
    the current interpreter. Returns its path (cleaned up alongside store_path).

    The wrapper is fixed text built only from sys.executable + this module's
    helper path -- no caller/credential input flows into it. git exec's it
    directly (no shell) with exactly one arg (the prompt). On Windows we forward
    that single arg as quoted `%~1` (NOT `%*`): git already passes the prompt as
    one argv element, and `%~1` re-quotes it as one token so a prompt containing
    cmd metacharacters (&, |, >) can never be re-parsed by cmd.exe. (Real ASKPASS
    invocation is shell-free and the prompt is git-generated, so this is
    defense-in-depth, not a live hole -- but `%~1` costs nothing.)"""
    helper = _ASKPASS_HELPER.as_posix()
    py = Path(sys.executable).as_posix()
    if os.name == "nt":
        fd, name = tempfile.mkstemp(prefix="bridge-askpass-", suffix=".cmd")
        body = f'@echo off\r\nsetlocal\r\n"{py}" "{helper}" "%~1"\r\n'
    else:
        fd, name = tempfile.mkstemp(prefix="bridge-askpass-", suffix=".sh")
        body = f'#!/bin/sh\nexec "{py}" "{helper}" "$1"\n'
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    if os.name != "nt":
        os.chmod(name, 0o700)
    return Path(name)


def _remote_default_branch(repo: str, cred: "_Cred") -> str | None:
    """Return the remote's default branch name (e.g. 'master', 'trunk'), or None.

    `git ls-remote --symref <repo> HEAD` prints a line
    ``ref: refs/heads/<name>\tHEAD`` naming the remote HEAD's target. We parse the
    branch out of that. Runs under the same resolved credential so a private repo
    answers (anonymous HEAD on a private repo is empty -> None, caller keeps the
    requested branch and lets the clone surface the real auth error)."""
    ls = _run_git(None, "ls-remote", "--symref", repo, "HEAD", cred=cred)
    if ls.returncode != 0:
        return None
    for line in ls.stdout.splitlines():
        line = line.strip()
        if line.startswith("ref:") and line.endswith("HEAD"):
            ref = line[len("ref:"):].rsplit("HEAD", 1)[0].strip()
            if ref.startswith("refs/heads/"):
                return ref[len("refs/heads/"):]
    return None


def _resolve_base_branch(repo: str, base_branch: str, cred: "_Cred") -> str:
    """Return base_branch if it exists on origin, else the remote's real default.

    The loop defaults base_branch to 'main', but plenty of repos still use
    'master' (or 'trunk'). Cloning --branch main against a master-only repo dies
    with the misleading 'Remote branch main not found in upstream origin'
    (observed 2026-06-06, dynamic-central-orchestrator -> rc=3). We probe the
    requested branch first; only when it is genuinely absent do we fall back to
    the remote HEAD's default, so an existing 'main' is never second-guessed and
    a transient/auth failure does not silently switch branches."""
    ls = _run_git(None, "ls-remote", "--heads", repo, base_branch, cred=cred)
    if ls.returncode == 0 and ls.stdout.strip():
        return base_branch  # requested branch exists -> use it
    if ls.returncode != 0:
        return base_branch  # probe failed (auth/transient) -> let clone surface it
    default = _remote_default_branch(repo, cred)
    return default or base_branch


def _git_clone_or_pull(repo: str, base_branch: str, workdir: Path,
                       prefer_branch: str | None = None) -> Path:
    """Clone repo@base_branch into workdir (fresh). If workdir exists, fetch and
    reset. When prefer_branch is given AND exists on origin, reset to it (so the
    loop continues its own prior work); otherwise reset to base_branch. Raises
    RuntimeError with stderr on failure."""
    workdir.parent.mkdir(parents=True, exist_ok=True)
    # Resolve HTTPS credentials once in the parent (GCM works here); empty _Cred
    # for local/ssh remotes or when nothing resolves. Reused for every git call
    # that touches the remote so the hardened child never falls back to anonymous.
    # The ephemeral store file (if any) is deleted in the finally below.
    cred = _resolve_https_credential(repo)
    try:
        if (workdir / ".git").exists():
            fetch = _run_git(workdir, "fetch", "origin", cred=cred)
            if fetch.returncode != 0:
                raise RuntimeError(f"git fetch failed: {fetch.stderr.strip()}")
            target = base_branch
            if prefer_branch:
                ls = _run_git(workdir, "ls-remote", "--heads", "origin",
                              prefer_branch, cred=cred)
                if ls.returncode == 0 and ls.stdout.strip():
                    target = prefer_branch
            for args in (
                ("checkout", target),
                ("reset", "--hard", f"origin/{target}"),
            ):
                cp = _run_git(workdir, *args)
                if cp.returncode != 0:
                    raise RuntimeError(f"git {args[0]} failed: {cp.stderr.strip()}")
            return workdir
        # On a FRESH clone, prefer the loop branch if it already exists on origin,
        # so the OTHER side's prior work continues instead of restarting from
        # base. This is the ping-pong continuity seam: A built on bridge/<loop_id>
        # and pushed it; B's workdir is fresh, so without this it would clone base
        # and silently drop A's commit (the next builder's work must build ON the
        # handoff, not beside it). The fetch/reset branch above already honoured
        # prefer_branch for an existing workdir; this closes the same gap for the
        # first clone.
        clone_branch = base_branch
        if prefer_branch:
            ls = _run_git(None, "ls-remote", "--heads", repo, prefer_branch,
                          cred=cred)
            if ls.returncode == 0 and ls.stdout.strip():
                clone_branch = prefer_branch
        cp = _run_git(None, "clone", "--branch", clone_branch, repo, str(workdir),
                      cred=cred)
        if cp.returncode != 0:
            raise RuntimeError(_diagnose_clone_failure(
                repo, clone_branch, cp.stderr.strip(), cred))
        # Ensure a committer identity exists for later commits (CI-less machine).
        _run_git(workdir, "config", "user.email", "bridge@laptop-b.local")
        _run_git(workdir, "config", "user.name", "dual-bridge-worker")
        return workdir
    finally:
        # Token-bearing store file + askpass wrapper must not outlive the git calls.
        cred.cleanup()


def _diagnose_clone_failure(repo: str, clone_branch: str, stderr: str,
                            cred: "_Cred") -> str:
    """Turn a raw clone stderr into an actionable message.

    Git reports a PRIVATE repo seen anonymously as 'Remote branch <b> not found
    in upstream origin' -- the branch is fine, the credential was not applied.
    We re-probe the remote with the same resolved credentials: if the branch IS
    visible, the clone's failure was auth/transient, so we say so instead of
    parroting the misleading 'branch not found' (which sent earlier debugging
    down the wrong path -- see _resolve_https_credential). If it is genuinely not
    visible, we keep git's own wording. NOTE: cred is the _Cred carrier, never
    rendered into the message -- the token must not reach a RuntimeError/log."""
    looks_like_missing_branch = "not found in upstream" in stderr.lower()
    if looks_like_missing_branch:
        # An empty _Cred (env={}) means _resolve_https_credential could not
        # resolve a token in the worker context AT ALL -- so this re-probe runs
        # just as anonymously as the failed clone did. Surface that up front: it
        # is the most common cause (observed 2026-06-06, three queued goal-loops
        # in a row) and the raw 'branch not found' would otherwise mislead again.
        no_cred = not cred.env
        ls = _run_git(None, "ls-remote", "--heads", repo, clone_branch,
                      cred=cred)
        if ls.returncode == 0 and ls.stdout.strip():
            hint = ("Branch existiert remote, der Clone bekam ihn aber nicht zu "
                    "sehen -> Auth/Token im Worker-Kontext greift nicht "
                    "(anonymer Fallback auf privates Repo). "
                    "Pruefe `git credential fill` im selben Kontext.")
            return f"git clone failed (AUTH, nicht fehlender Branch): {hint} -- git: {stderr}"
        if ls.returncode != 0:
            return (f"git clone failed: Remote nicht erreichbar/auth "
                    f"(ls-remote rc={ls.returncode}: {ls.stderr.strip()}) -- "
                    f"git: {stderr}")
        # rc==0 but EMPTY ref list. Either (a) we have no credential, so the
        # probe is anonymous and a private repo legitimately shows zero refs --
        # almost certainly auth, not a missing branch; or (b) we DID resolve a
        # credential yet still see nothing, meaning the branch truly is absent
        # (or the repo is empty). Distinguish the two so the escalation points at
        # the right fix instead of parroting git's misleading wording.
        if no_cred:
            hint = ("Keine Credential im Worker-Kontext aufloesbar "
                    "(_resolve_https_credential -> leer), der Re-Probe lief "
                    "daher ebenfalls anonym und sah 0 Refs. Bei einem PRIVATEN "
                    "Repo ist das das erwartete Symptom -> Auth, nicht fehlender "
                    "Branch. Pruefe `git credential fill` im selben (gehaerteten) "
                    "Kontext.")
            return f"git clone failed (AUTH, nicht fehlender Branch): {hint} -- git: {stderr}"
        return (f"git clone failed: Branch {clone_branch!r} remote nicht "
                f"sichtbar trotz aufgeloester Credential (Repo leer oder Branch "
                f"existiert wirklich nicht) -- git: {stderr}")
    return f"git clone failed: {stderr}"


def _git_checkout_branch(workdir: Path, branch: str) -> None:
    """Create/reset the task branch (force, so a repeated task_id is repairable)."""
    cp = _run_git(workdir, "checkout", "-B", branch)
    if cp.returncode != 0:
        raise RuntimeError(f"git checkout -B failed: {cp.stderr.strip()}")


def _git_status_porcelain(workdir: Path) -> list[str]:
    """Return list of changed paths (porcelain). Empty list = clean tree."""
    cp = _run_git(workdir, "status", "--porcelain")
    return [ln[3:].strip() for ln in cp.stdout.splitlines() if ln.strip()]


def _commits_ahead_of_base(workdir: Path, base_branch: str) -> list[str]:
    """Short hashes of commits on HEAD not yet on origin/base (newest first).

    codex-cli 0.136 under -s danger-full-access may commit its OWN change, which
    leaves the working tree clean — so `git status --porcelain` says "nothing
    changed" while HEAD is genuinely ahead of origin/base. Detecting progress by
    porcelain status alone then drops a real, committed build (seed-02 round-2
    empty-diff bug, 2026-06-03). This counts the committed-but-unpushed work the
    porcelain check is blind to. Empty list = HEAD really is at origin/base."""
    cp = _run_git(workdir, "rev-list", f"origin/{base_branch}..HEAD")
    if cp.returncode != 0:
        return []
    return [ln.strip()[:7] for ln in cp.stdout.splitlines() if ln.strip()]


def _changed_files_vs_base(workdir: Path, base_branch: str) -> list[str]:
    """Files changed between origin/base and HEAD (for a self-committed build,
    where `git status --porcelain` is clean but commits carry the real change)."""
    cp = _run_git(workdir, "diff", "--name-only", f"origin/{base_branch}...HEAD")
    if cp.returncode != 0:
        return []
    return [ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]


def _git_commit_and_push(workdir: Path, branch: str, message: str) -> str:
    """Add+commit all changes and push the branch (force-with-lease). Returns
    the commit hash. Raises RuntimeError(stderr) on commit/push failure, but the
    caller catches push failures separately to keep the answer."""
    add = _run_git(workdir, "add", "-A")
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.strip()}")
    commit = _run_git(workdir, "commit", "-m", message)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {commit.stderr.strip()}")
    rev = _run_git(workdir, "rev-parse", "--short", "HEAD")
    commit_hash = rev.stdout.strip()
    push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
    if push.returncode != 0:
        raise RuntimeError(f"PUSH_FAILED::{commit_hash}::{push.stderr.strip()}")
    return commit_hash


_DIFF_LIMIT = 60_000  # chars; over this we truncate the review payload honestly


def _git_diff(workdir: Path, base_branch: str) -> str:
    """Unified diff of the build vs base (origin/base...HEAD). Truncated to
    _DIFF_LIMIT with an explicit marker (never a silent cap)."""
    cp = _run_git(workdir, "diff", f"origin/{base_branch}...HEAD")
    text = cp.stdout or ""
    if len(text) > _DIFF_LIMIT:
        text = (text[:_DIFF_LIMIT]
                + f"\n\n[... Diff bei {_DIFF_LIMIT} Zeichen abgeschnitten "
                  f"(Gesamtlaenge {len(cp.stdout)}); Reviewer urteilt auf dem "
                  "gezeigten Ausschnitt ...]\n")
    return text


def _build_codex_cmd(codex_exe: str, workdir: Path, answer_file: Path) -> list[str]:
    """Assemble the `codex exec` argv for one non-interactive build.

    Flags verified against codex-cli 0.136 (`codex exec --help`):
      -C <workdir>            explicit working root
      -s danger-full-access   NO sandbox. Required, not a convenience: codex
                              0.136's Windows workspace-write sandbox blocks
                              pytest's tmp_path_factory / .pytest_cache writes
                              (they land in %TEMP%, outside the writable roots,
                              and --add-dir does not reliably whitelist %TEMP%
                              on Windows). A seed whose done-criteria run the
                              test suite then fails every test at fixture setup
                              with WinError 5, sends codex into an exploratory
                              %TEMP%-probing shell loop, and the synchronous
                              no-timeout superpowers SessionStart hook
                              (cmd->bash polyglot) deadlocks there -> the whole
                              python->node->codex.exe tree hangs past `timeout`.
                              Dropping the sandbox is safe HERE because the
                              workdir is itself a throwaway clone isolated from
                              the real repo, and the loop draws the real
                              boundary (allowlist + escalate-on-dangerous).
                              (Root-caused 2026-06-03, seed-02 hang.)
      -c approval_policy="never"
                              exec is non-interactive: with the default
                              escalate-to-user policy a write that needs
                              approval can never get it, so codex reports
                              "read-only / approvals disabled" and then probes
                              for a writable dir -> same hang path. "never"
                              makes failures return immediately instead.
      --skip-git-repo-check   the workdir is a freshly cloned+branched git repo
                              by construction; codex 0.135+ otherwise refuses on
                              a tree it doesn't recognise as trusted.
      -o <answer.txt>         final agent message to a file (robust; sidesteps
                              the BOM/event-stream/hook-noise stdout parsing of
                              L17). Lives OUTSIDE the workdir so `git status`
                              never picks it up.
      -                       prompt via STDIN, NOT as a CLI arg (rule 10.8 /
                              P008): a long prompt with backticks/parens/newlines
                              as an argument is mangled by B's codex.CMD wrapper
                              at the cmd.exe quoting layer.
    """
    return [
        codex_exe, "exec",
        "-C", str(workdir),
        "-s", "danger-full-access",
        "-c", 'approval_policy="never"',
        "--skip-git-repo-check",
        "-o", str(answer_file),
        "-",
    ]


def run_codex_task(
    auftrag: str,
    repo: str,
    base_branch: str,
    task_id: str,
    workroot: Path,
    codex_bin: str | None = None,
    timeout: int = 600,
    branch: str | None = None,
    workdir_name: str | None = None,
) -> CodexResult:
    """Run one task end-to-end on Laptop B. Every path returns a CodexResult
    with status done|error -- never raises to the caller (spec section 5: no
    stuck, no silent failure).

    workdir_name overrides the per-task working-dir name (default: task_id). The
    build-review loop passes a stable loop_id so all rounds share one workdir and
    round 2+ continues from the loop branch instead of re-cloning base.
    """
    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        import fnmatch
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return CodexResult(status="error",
                               error_text=f"repo nicht in allowlist abgelehnt: {repo}")

    branch = branch or f"bridge/task-{task_id}"

    # 1. codex on PATH?
    codex_exe = codex_bin or shutil.which("codex")
    if not codex_exe:
        return CodexResult(status="error",
                           error_text="codex nicht gefunden -- auf B installiert/im PATH?")

    # 2. repo reachable?
    workdir = Path(workroot) / (workdir_name or task_id)
    # Resolve the real base branch BEFORE any git op: the loop defaults to 'main',
    # but a 'master'/'trunk' repo would otherwise fail every clone/rev-list/diff
    # (they all reference origin/<base_branch>). One credential resolve here; the
    # store file is ephemeral and cleaned up in the finally.
    #
    # This MUST run every round, not only on a fresh workdir. base_branch is a
    # per-call local the loop re-supplies as 'main' each round — it is NOT
    # persisted. Skipping the probe on an existing workdir (round 2+) therefore
    # left base_branch='main' on a master-only repo, so `git diff origin/main...
    # HEAD` died and the reviewer got an EMPTY diff -> rejected -> max_rounds
    # escalation, even though codex had built correctly (reminders-v2 Paket B,
    # loop ...4905, 2026-06-07). The redundant ls-remote per round is cheap
    # insurance against that silent continuity break.
    _bb_cred = _resolve_https_credential(repo)
    try:
        base_branch = _resolve_base_branch(repo, base_branch, _bb_cred)
    finally:
        _bb_cred.cleanup()
    try:
        _git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 3. task branch
    try:
        _git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return CodexResult(status="error", error_text=str(exc))

    # 4. codex exec -- argv assembled by _build_codex_cmd (flags + rationale
    #    documented there; verified against codex-cli 0.136). The -o answer file
    #    lives OUTSIDE the workdir, so it can never be picked up by `git status`.
    answer_file = Path(workroot) / f".codex-answer-{task_id}.txt"
    cmd = _build_codex_cmd(codex_exe, workdir, answer_file)
    try:
        proc = subprocess.run(
            cmd, cwd=str(workdir), capture_output=True, text=True,
            encoding="utf-8", input=auftrag, timeout=timeout,
            env=safe_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex timeout nach {timeout}s",
                           stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        # An explicit codex_bin that does not exist (or is not executable) must
        # not raise out of here — the spec guarantees a CodexResult on every path.
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex nicht ausführbar ({codex_exe}): {exc}")
    if proc.returncode != 0:
        _safe_unlink(answer_file)
        return CodexResult(status="error",
                           error_text=f"codex exit {proc.returncode}",
                           stderr_excerpt=_tail(proc.stderr))

    # 5. answer: prefer the -o file, fall back to parsing stdout (both robust).
    antwort = ""
    if answer_file.exists():
        antwort = parse_codex_output(answer_file.read_text(encoding="utf-8-sig"))
        _safe_unlink(answer_file)
    if not antwort:
        antwort = parse_codex_output(proc.stdout)
    if not antwort:
        return CodexResult(status="error", error_text="codex: leere Antwort",
                           stderr_excerpt=_tail(proc.stderr))

    # 6. did codex change files? Two ways forward: an uncommitted working-tree
    #    change (we commit it), OR codex already self-committed (0.136 under
    #    danger-full-access) so the tree is clean but HEAD is ahead of base. Only
    #    when BOTH are empty did codex truly produce no change.
    changed = _git_status_porcelain(workdir)
    if not changed:
        ahead = _commits_ahead_of_base(workdir, base_branch)
        if ahead:
            # codex self-committed: surface its commit + diff as real progress
            # instead of dropping it as "no change" (seed-02 round-2 bug). The
            # commit is local-only — push it, or the next round's clone_or_pull
            # resets --hard to origin/<branch> and drops it (continuity break,
            # Codex review MAJOR 2026-06-03). On push failure keep the local hash
            # but flag it, mirroring the normal commit+push path below.
            diff = _git_diff(workdir, base_branch)
            changed_files = _changed_files_vs_base(workdir, base_branch)
            push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
            if push.returncode != 0:
                return CodexResult(status="error", antwort=antwort, branch=branch,
                                   commit=ahead[0], changed_files=changed_files,
                                   diff=diff,
                                   error_text=f"push fehlgeschlagen (lokaler Commit "
                                              f"{ahead[0]} auf B)",
                                   stderr_excerpt=_tail(push.stderr))
            return CodexResult(status="done", antwort=antwort, branch=branch,
                               commit=ahead[0], changed_files=changed_files,
                               diff=diff)
        return CodexResult(status="done", antwort=antwort, branch=None,
                           commit=None, changed_files=[],
                           note="codex gab nur Text, keine Datei-Aenderung")

    # 7. commit + push (keep answer even if push fails)
    try:
        commit = _git_commit_and_push(workdir, branch, f"bridge: task {task_id}")
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("PUSH_FAILED::"):
            _, local_hash, stderr = msg.split("::", 2)
            return CodexResult(status="error", antwort=antwort, branch=branch,
                               commit=local_hash, changed_files=changed,
                               error_text=f"push fehlgeschlagen (lokaler Commit {local_hash} auf B)",
                               stderr_excerpt=_tail(stderr))
        return CodexResult(status="error", antwort=antwort, branch=branch,
                           changed_files=changed, error_text=msg)
    diff = _git_diff(workdir, base_branch)
    return CodexResult(status="done", antwort=antwort, branch=branch,
                       commit=commit, changed_files=changed, diff=diff)


def _tail(text: str | None, limit: int = 2000) -> str | None:
    """Last `limit` chars of stderr, for an error excerpt."""
    if not text:
        return None
    return text[-limit:]


def _safe_unlink(path: Path) -> None:
    """Delete a file if present; never raise (best-effort cleanup)."""
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _codex_runner(auftrag: str, fm: dict, workroot):
    """Adapt run_codex_task to the (auftrag, fm, workroot) runner signature."""
    task_id = fm.get("task_id")
    if not task_id:
        return RunnerResult(status="error", error_text="task ohne task_id")
    wr = Path(workroot) if workroot is not None else Path.home() / "dual-bridge-work"
    return run_codex_task(
        auftrag=auftrag,
        repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"),
        task_id=task_id,
        workroot=wr,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=config_value(
            "codex_timeout", "DUAL_BRIDGE_CODEX_TIMEOUT", 600, cast=int),
        branch=fm.get("branch"),
        workdir_name=fm.get("workdir_name"),
    )


register_runner("codex", _codex_runner)
