"""Runner registry for the Dual-Laptop-Bridge (Stage 2a).

A runner is a function (auftrag, fm, workroot) -> RunnerResult. The result type
is shared by all runners; git-publishing is NOT part of the contract (only the
codex runner pushes a branch). Pure stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class RunnerResult:
    status: str                       # "done" | "error"
    antwort: str = ""
    branch: str | None = None
    commit: str | None = None
    changed_files: list[str] = field(default_factory=list)
    error_text: str | None = None
    stderr_excerpt: str | None = None
    note: str | None = None
    diff: str | None = None            # unified diff of the build (review payload)
    verdict: str | None = None         # "accepted" | "rejected" (review kind only)
    verdict_reason: str | None = None

    def to_markdown(self, task_id: str, claimed_by: str, claimed_at: str) -> str:
        lines = ["## Quelle",
                 f"task_id {task_id}, geclaimt von {claimed_by} um {claimed_at}", ""]
        if self.status == "done":
            lines += ["## Antwort", self.antwort, ""]
            if self.verdict:
                lines += ["## Verdikt", f"verdict: {self.verdict}"]
                if self.verdict_reason:
                    lines += [f"verdict_reason: {self.verdict_reason}"]
                lines += [""]
            if self.branch and self.commit:
                lines += [
                    "## Artefakt (Git)",
                    f"Branch `{self.branch}` auf dem Remote, Commit `{self.commit}`.",
                    f"Geänderte Dateien: {', '.join(self.changed_files) or '—'}",
                    "", "## So holst du es",
                    "```", f"git fetch && git checkout {self.branch}", "```", "",
                ]
            elif self.note:
                lines += ["## Hinweis", self.note, ""]
        else:
            lines += ["## FEHLER", self.error_text or "unbekannter Fehler", ""]
            if self.antwort:
                lines += ["## Antwort (trotz Fehler erhalten)", self.antwort, ""]
            if self.stderr_excerpt:
                lines += ["## stderr (Auszug)", "```", self.stderr_excerpt, "```", ""]
        return "\n".join(lines)


def run_echo(auftrag: str, fm: dict, workroot: Path | None) -> RunnerResult:
    """Stage-0 echo: reflect the auftrag back, no LLM.

    Two modes, picked by whether fm carries a non-empty `repo`:

    * No repo (back-compat: ping-pong / handoff echo) — pure text reflector, no
      git, no commit. This is the original behaviour.
    * Repo set (the DCO bridge runs every job as a goal-loop and hands the runner
      a loop branch) — clone that branch and commit a deterministic marker file
      so the build DIFF is non-empty. The pure-text echo produced an EMPTY diff,
      so the smoke preset (echo·echo) could never be accepted by the diff-judging
      reviewer and always escalated on max_rounds (#7903 / L20). The marker lets
      the smoke exercise the FULL pipeline (clone→commit→review→accept→merge)
      instead of only the transport layer."""
    if (fm or {}).get("repo"):
        return _run_echo_build(auftrag, fm, workroot)
    return RunnerResult(
        status="done",
        antwort=(f"{auftrag}\n\n(Echo — Laptop hat den Task gelesen und den "
                 "Auftragstext zurückgespiegelt. Kein LLM.)"),
    )


# Single, fixed marker path (NOT a per-task filename): with merge_on_accept on
# (permanently on for Laptop A), a per-task name would accumulate one file per
# smoke in the target repo's base. One updating file keeps the footprint at
# exactly one tracked file. The task_id lives in the CONTENT so every smoke
# still produces a non-empty diff even when the base already carries the marker
# (the exact L20 failure mode). Repo-root path: never gitignored (the bridge
# only ignores scripts/state/), repo-agnostic.
ECHO_SMOKE_MARKER = "bridge-smoke.txt"


def _run_echo_build(auftrag: str, fm: dict, workroot: Path | None) -> RunnerResult:
    """Git-aware echo: commit a deterministic marker on the loop branch.

    Mirrors codex_adapter.run_codex_task's git scaffolding (allowlist, base-branch
    resolve, clone_or_pull onto the loop branch, checkout, commit+push, diff) but
    replaces the codex exec with a single marker write. adapter_git is imported
    lazily so the pure-text echo path (and runners' import surface) never pulls in
    the git machinery."""
    import os
    import fnmatch
    import adapter_git  # lazy: avoid import-time coupling to the git layer

    task_id = (fm or {}).get("task_id")
    if not task_id:
        return RunnerResult(status="error", error_text="echo-build: task ohne task_id")
    repo = fm["repo"]
    base_branch = fm.get("base_branch", "main")
    branch = fm.get("branch") or f"bridge/task-{task_id}"
    workdir_name = fm.get("workdir_name") or task_id
    wr = Path(workroot) if workroot is not None else Path.home() / "dual-bridge-work"

    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return RunnerResult(status="error",
                                error_text=f"repo nicht in allowlist abgelehnt: {repo}")

    workdir = wr / workdir_name
    # Resolve the real base branch BEFORE any git op (a master/trunk repo would
    # otherwise fail every clone/diff against origin/main) — same per-round probe
    # as the codex adapter, one ephemeral credential resolve cleaned up here.
    cred = adapter_git._resolve_https_credential(repo)
    try:
        base_branch = adapter_git._resolve_base_branch(repo, base_branch, cred)
    finally:
        cred.cleanup()
    try:
        adapter_git._git_clone_or_pull(repo, base_branch, workdir, prefer_branch=branch)
        adapter_git._git_checkout_branch(workdir, branch)
    except RuntimeError as exc:
        return RunnerResult(status="error", error_text=str(exc))

    marker = workdir / ECHO_SMOKE_MARKER
    marker.write_text(f"bridge-smoke {task_id} ok\n", encoding="utf-8")

    changed = adapter_git._git_status_porcelain(workdir)
    if not changed:
        # Marker content was byte-identical to what the base already carried — a
        # genuinely empty diff. Should not happen (task_id is unique) but never
        # masquerade as a build: surface it as an error so the loop does not see
        # a phantom done with no diff.
        return RunnerResult(status="error",
                            error_text="echo-build: Marker erzeugte keinen Diff "
                                       "(Inhalt unverändert)")
    try:
        commit = adapter_git._git_commit_and_push(
            workdir, branch, f"bridge: smoke {task_id}")
    except RuntimeError as exc:
        msg = str(exc)
        if msg.startswith("PUSH_FAILED::"):
            _, local_hash, stderr = msg.split("::", 2)
            return RunnerResult(status="error", branch=branch, commit=local_hash,
                                changed_files=changed,
                                error_text=f"push fehlgeschlagen (lokaler Commit "
                                           f"{local_hash} auf B)",
                                stderr_excerpt=stderr[-2000:] if stderr else None)
        return RunnerResult(status="error", branch=branch, changed_files=changed,
                            error_text=msg)
    diff = adapter_git._git_diff(workdir, base_branch)
    changed_files = adapter_git._changed_files_vs_base(workdir, base_branch)
    return RunnerResult(
        status="done",
        antwort=(f"Echo-Smoke: Marker `{ECHO_SMOKE_MARKER}` auf `{branch}` "
                 f"committet ({task_id}). Kein LLM."),
        branch=branch, commit=commit, changed_files=changed_files, diff=diff,
    )


def run_increment(auftrag: str, fm: dict, workroot: Path | None) -> RunnerResult:
    """Stage-1 loop work: read the loop payload as an int and return +1.

    The payload travels in fm['payload'] (the loop envelope). Falls back to
    `auftrag` when fm has no payload (e.g. a plain CLI task). A non-numeric
    payload is a hard error — never a silent default."""
    raw = fm.get("payload", auftrag)
    try:
        nxt = int(str(raw).strip()) + 1
    except (TypeError, ValueError):
        return RunnerResult(
            status="error",
            error_text=f"increment: payload {raw!r} ist keine ganze Zahl",
        )
    return RunnerResult(status="done", antwort=str(nxt))


# Populated here for echo; codex/claude register themselves via register_runner
# from their own modules to avoid import cycles with bridge code.
RUNNERS: dict[str, Callable[..., RunnerResult]] = {"echo": run_echo}


def register_runner(name: str, fn: Callable[..., RunnerResult]) -> None:
    RUNNERS[name] = fn


register_runner("increment", run_increment)
