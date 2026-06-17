"""Shared git scaffolding for building bridge adapters (extracted 2026-06-12).

Owns the git clone/branch/commit/push dance that any BUILDING adapter needs:
credential resolution (GIT_ASKPASS, no secrets in argv/env), base-branch
resolution, workdir lifecycle, diff/status against base, commit+push, and the
merge-on-accept / escalation-push helpers used by the goal loop.

Extracted verbatim from codex_adapter.py (spec
docs/superpowers/specs/2026-06-12-adapter-git-extraction-design.md) as the
groundwork for a future claude builder. Names keep their original underscore
prefixes on purpose: minimal-diff extraction, monkeypatch targets stay stable.
codex_adapter re-exports everything as a back-compat shim. Pure stdlib.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from bridge_common import safe_subprocess_env

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class BuildOutcome(NamedTuple):
    status: str                    # "done" | "error"
    branch: str | None
    commit: str | None
    changed_files: list
    diff: str | None
    error_text: str | None
    stderr_excerpt: str | None
    note: str | None


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
        stdin=subprocess.DEVNULL, env=env, creationflags=_NO_WINDOW,
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
        encoding="utf-8", env=safe_subprocess_env(), creationflags=_NO_WINDOW,
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


def merge_accepted_to_base(repo: str, branch: str, base_branch: str,
                           workdir: Path) -> str:
    """Merge an accepted loop branch into base_branch and push it.

    Why: each loop clones fresh from base_branch, so a multi-package feature
    where 'Paket B baut auf A' only works if A's accepted build is integrated
    into base_branch BEFORE B's loop clones it. Without this the next package
    re-clones a base that never saw the prior one and starts from scratch
    (observed 2026-06-07, reminders-v2 A/B/C/D never accumulated).

    Reuses the loop's existing workdir (origin + the accepted branch are already
    there). Fetches, checks out base_branch tracking origin/base, merges the loop
    branch with an explicit --no-ff merge commit, and pushes base. Returns the
    short hash of the new base HEAD.

    Fail-soft contract: raises RuntimeError on any git failure (merge conflict,
    push reject, missing branch) so the caller can record 'accepted but NOT
    merged' WITHOUT losing the accepted verdict. Never silently swallows a
    conflict — an unmerged accept must be visible, not pretended."""
    cred = _resolve_https_credential(repo)
    try:
        # Resolve main->master/trunk here too: the caller (loop_driver) hands in
        # the unresolved 'main' default, so a master-only repo would die with
        # 'origin/main is not a commit' AFTER an accepted build — the build path
        # resolves the base but the merge path did not (live regression
        # 2026-06-07, reminders Paket A). Same probe the build uses.
        base_branch = _resolve_base_branch(repo, base_branch, cred)
        fetch = _run_git(workdir, "fetch", "origin", cred=cred)
        if fetch.returncode != 0:
            raise RuntimeError(f"fetch failed: {fetch.stderr.strip()}")
        # Check out base tracking origin/base so the merge target is the remote
        # tip, not a stale local copy. -B re-points an existing local base too.
        co = _run_git(workdir, "checkout", "-B", base_branch,
                      f"origin/{base_branch}", cred=cred)
        if co.returncode != 0:
            raise RuntimeError(f"checkout {base_branch} failed: {co.stderr.strip()}")
        merge = _run_git(workdir, "merge", "--no-ff", branch,
                         "-m", f"bridge: merge accepted {branch} into {base_branch}",
                         cred=cred)
        if merge.returncode != 0:
            # Abort the half-done merge so the workdir is not left mid-conflict
            # (the next round's clone_or_pull reset would otherwise trip over it).
            _run_git(workdir, "merge", "--abort")
            raise RuntimeError(f"merge conflict {branch} -> {base_branch}: "
                               f"{merge.stdout.strip() or merge.stderr.strip()}")
        rev = _run_git(workdir, "rev-parse", "--short", "HEAD")
        push = _run_git(workdir, "push", "origin", base_branch, cred=cred)
        if push.returncode != 0:
            raise RuntimeError(f"push {base_branch} failed: {push.stderr.strip()}")
        return rev.stdout.strip()
    finally:
        cred.cleanup()


def push_branch_on_escalation(repo: str, branch: str, workdir: Path) -> bool:
    """Push the loop branch to origin when a goal-loop escalates (exit 3).

    Why: an escalated branch holds finished, often-mergeable code. The DCO-side
    'Prüfen & Mergen' button fetches it from origin to gate-check + merge. Only
    the ACCEPTED path pushed historically (merge_accepted_to_base), so an
    escalated branch could live only locally on the builder (observed 2026-06-07,
    reminders-D). Reuses the loop's workdir (origin + the branch are already
    there) and the same GIT_ASKPASS credential handling as the accept-push so a
    PRIVATE repo is not cloned anonymously under the hardened sandbox.

    Best-effort contract: returns True on a successful push, False on ANY failure
    (git error, missing branch, credential blow-up) — it NEVER raises. Escalation
    must complete regardless; the DCO button falls back to a 'branch not on
    origin' manual hint when the push did not land."""
    try:
        cred = _resolve_https_credential(repo)
    except Exception:
        return False
    try:
        push = _run_git(workdir, "push", "origin", f"{branch}:{branch}", cred=cred)
        return push.returncode == 0
    except Exception:
        return False
    finally:
        try:
            cred.cleanup()
        except Exception:
            pass


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


def _git_diff_since(workdir: Path, since_ref: str) -> str:
    """Unified diff of what was added since `since_ref` (since_ref...HEAD).

    The relay-loop uses this so the reviewer judges only THIS round's increment,
    not the whole accumulated branch (which grows every round). Same _DIFF_LIMIT
    truncation as _git_diff (never a silent cap)."""
    cp = _run_git(workdir, "diff", f"{since_ref}...HEAD")
    text = cp.stdout or ""
    if len(text) > _DIFF_LIMIT:
        text = (text[:_DIFF_LIMIT]
                + f"\n\n[... Diff bei {_DIFF_LIMIT} Zeichen abgeschnitten "
                  f"(Gesamtlaenge {len(cp.stdout)}); Reviewer urteilt auf dem "
                  "gezeigten Ausschnitt ...]\n")
    return text


def _tail(text: str | None, limit: int = 2000) -> str | None:
    """Last `limit` chars of text, for error excerpts. Returns None for empty input."""
    if not text:
        return None
    return text[-limit:]


def finalize_build(workdir: Path, branch: str, base_branch: str,
                   commit_msg: str,
                   no_change_note: str = "nur Text, keine Datei-Aenderung",
                   ) -> BuildOutcome:
    """Detect a builder's changes (uncommitted working-tree OR a self-commit that
    left HEAD ahead of base), commit+push when needed, and return the diff.

    Shared by the codex and claude builders. Never raises. The self-commit branch
    force-with-lease pushes the agent's own commit so the next round's
    clone_or_pull (reset --hard origin/<branch>) cannot drop it (continuity,
    Codex review MAJOR 2026-06-03).
    """
    changed = _git_status_porcelain(workdir)
    if not changed:
        ahead = _commits_ahead_of_base(workdir, base_branch)
        if ahead:
            diff = _git_diff(workdir, base_branch)
            changed_files = _changed_files_vs_base(workdir, base_branch)
            push = _run_git(workdir, "push", "--force-with-lease", "origin", branch)
            if push.returncode != 0:
                return BuildOutcome("error", branch, ahead[0], changed_files, diff,
                                    f"push fehlgeschlagen (lokaler Commit {ahead[0]} auf B)",
                                    _tail(push.stderr), None)
            return BuildOutcome("done", branch, ahead[0], changed_files, diff,
                                None, None, None)
        return BuildOutcome("done", None, None, [], None, None, None, no_change_note)
    try:
        commit = _git_commit_and_push(workdir, branch, commit_msg)
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("PUSH_FAILED::"):
            _, local_hash, stderr = msg.split("::", 2)
            return BuildOutcome("error", branch, local_hash, changed, None,
                                f"push fehlgeschlagen (lokaler Commit {local_hash} auf B)",
                                _tail(stderr), None)
        return BuildOutcome("error", branch, None, changed, None, msg, None, None)
    diff = _git_diff(workdir, base_branch)
    return BuildOutcome("done", branch, commit, changed, diff, None, None, None)
