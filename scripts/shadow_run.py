"""Run one goal-loop seed twice and print only the result diff.

The production CLI creates two isolated run roots (main + shadow), clones the
source repo into separate local bare origins, runs the same seed with the same
deterministic loop_id, and compares only the verdict/commit projection. Tests
inject the run function and repo factory so they never touch Codex, a network
remote, or the project origin.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import bridge_common as bc
import loop_driver

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


RUN_LABELS = ("main", "shadow")
DEFAULT_SHADOW_ROOT = Path(__file__).resolve().parent / "state" / "_shadow_runs"

KNOWN_NONDETERMINISM_SOURCES = [
    "git commit timestamps can change final_commit for identical trees",
    "microsecond/uuid task ids can leak into branches, prompts, or artifacts",
    "filesystem or queue ordering effects if discovery is not explicitly sorted",
]


@dataclass(frozen=True)
class ShadowContext:
    label: str
    seed_text: str
    goal: str
    done_criteria: list[str]
    repo: str
    base_branch: str
    max_rounds: int
    round_timeout: int
    interval: float
    loop_id: str
    run_root: Path
    bridge_root: Path
    state_dir: Path
    lock_path: Path
    result_dir: Path
    field_notes_dir: Path
    review_mode: str
    codex_bin: str | None = None


@dataclass(frozen=True)
class ShadowPairResult:
    main: dict
    shadow: dict
    main_context: ShadowContext
    shadow_context: ShadowContext

    @property
    def has_diff(self) -> bool:
        return self.main != self.shadow


RepoFactory = Callable[..., str]
RunOnceFn = Callable[[ShadowContext], dict]


def deterministic_loop_id(seed_text: str, *, base_branch: str, max_rounds: int,
                          round_timeout: int) -> str:
    """Stable loop id for both runs, avoiding an expected branch-name diff."""
    h = hashlib.sha256()
    h.update(seed_text.encode("utf-8"))
    h.update(b"\0")
    h.update(base_branch.encode("utf-8"))
    h.update(b"\0")
    h.update(str(max_rounds).encode("ascii"))
    h.update(b"\0")
    h.update(str(round_timeout).encode("ascii"))
    return f"loop-shadow-{h.hexdigest()[:12]}"


def run_shadow_pair(
    *,
    seed_text: str,
    source_repo: Path,
    work_root: Path,
    base_branch: str = "main",
    max_rounds: int = 4,
    round_timeout: int = 600,
    interval: float = 5.0,
    loop_id: str | None = None,
    review_mode: str = "auto-accept",
    codex_bin: str | None = None,
    repo_factory: RepoFactory | None = None,
    run_once_fn: RunOnceFn | None = None,
) -> ShadowPairResult:
    """Run the same seed as main + shadow and return comparable projections."""
    goal, criteria = loop_driver.parse_seed(seed_text)
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    loop_id = loop_id or deterministic_loop_id(
        seed_text, base_branch=base_branch, max_rounds=max_rounds,
        round_timeout=round_timeout)
    repo_factory = repo_factory or create_throwaway_origin
    run_once_fn = run_once_fn or _real_run_once

    projections: dict[str, dict] = {}
    contexts: dict[str, ShadowContext] = {}
    for label in RUN_LABELS:
        run_root = work_root / label
        run_root.mkdir(parents=True, exist_ok=True)
        repo = repo_factory(
            source_repo=Path(source_repo), run_root=run_root, label=label,
            base_branch=base_branch)
        ctx = ShadowContext(
            label=label,
            seed_text=seed_text,
            goal=goal,
            done_criteria=list(criteria),
            repo=str(repo),
            base_branch=base_branch,
            max_rounds=max_rounds,
            round_timeout=round_timeout,
            interval=interval,
            loop_id=loop_id,
            run_root=run_root,
            bridge_root=run_root / "bridge-root",
            state_dir=run_root / "state",
            lock_path=run_root / "locks" / "dual-bridge-loop.lock",
            result_dir=run_root / "results",
            field_notes_dir=run_root / "field-notes",
            review_mode=review_mode,
            codex_bin=codex_bin,
        )
        summary = run_once_fn(ctx)
        projection = project_result(summary, ctx)
        _write_result(ctx, projection)
        contexts[label] = ctx
        projections[label] = projection

    return ShadowPairResult(
        main=projections["main"],
        shadow=projections["shadow"],
        main_context=contexts["main"],
        shadow_context=contexts["shadow"],
    )


def project_result(summary: dict, ctx: ShadowContext) -> dict:
    """Project loop output down to verdict/commit fields worth diffing."""
    accepted = bool(summary.get("accepted"))
    escalated = bool(summary.get("escalated"))
    trigger = str(summary.get("escalation_trigger") or "")
    if accepted:
        verdict = "accepted"
    elif escalated:
        verdict = f"escalated:{trigger or 'unknown'}"
    else:
        verdict = "not_accepted"
    final_commit = str(summary.get("final_commit") or "")
    return {
        "loop_id": str(summary.get("loop_id") or ctx.loop_id),
        "verdict": verdict,
        "rounds_done": int(summary.get("rounds_done") or 0),
        "final_branch": str(summary.get("final_branch") or f"bridge/{ctx.loop_id}"),
        "commit_result": {
            "commit_ahead": bool(final_commit),
            "final_commit": final_commit,
            "known_nondeterminism_sources": KNOWN_NONDETERMINISM_SOURCES,
        },
        "review_result": {
            "escalation_trigger": trigger,
        },
    }


def render_diff(result: ShadowPairResult) -> str:
    """Unified diff of the two comparable result projections. Empty means equal."""
    left = json.dumps(result.main, ensure_ascii=False, indent=2).splitlines()
    right = json.dumps(result.shadow, ensure_ascii=False, indent=2).splitlines()
    lines = list(difflib.unified_diff(
        left, right, fromfile="main", tofile="shadow", lineterm="", n=5))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _write_result(ctx: ShadowContext, projection: dict) -> None:
    target_dir = ctx.result_dir if ctx.label == "main" else ctx.field_notes_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    bc.write_text_atomic(
        target_dir / "result.json",
        json.dumps(projection, ensure_ascii=False, indent=2),
    )


def create_throwaway_origin(*, source_repo: Path, run_root: Path, label: str,
                            base_branch: str) -> str:
    """Create a local bare origin for one run. No network remote is used."""
    source = Path(source_repo).resolve()
    if not source.exists():
        raise RuntimeError(f"source repo does not exist: {source}")
    origin = Path(run_root) / f"{label}-origin.git"
    if origin.exists():
        raise RuntimeError(
            f"throwaway origin already exists: {origin} "
            "(choose a fresh --work-root)")
    cp = _run_git(
        None, "clone", "--bare", "--branch", base_branch, str(source), str(origin))
    if cp.returncode != 0:
        raise RuntimeError(f"git clone --bare failed: {cp.stderr.strip()}")
    return str(origin)


def _real_run_once(ctx: ShadowContext) -> dict:
    """Run loop_driver.run_goal_loop in one isolated bridge/state root."""
    ctx.bridge_root.mkdir(parents=True, exist_ok=True)
    ctx.state_dir.mkdir(parents=True, exist_ok=True)
    ctx.lock_path.parent.mkdir(parents=True, exist_ok=True)
    b_tick = None if ctx.review_mode == "external" else _auto_accept_result

    with _isolated_loop_env(ctx):
        return loop_driver.run_goal_loop(
            goal=ctx.goal,
            done_criteria=ctx.done_criteria,
            repo=ctx.repo,
            base_branch=ctx.base_branch,
            max_rounds=ctx.max_rounds,
            round_timeout=ctx.round_timeout,
            interval=ctx.interval,
            build_runner=None,
            b_tick=b_tick,
            loop_id=ctx.loop_id,
        )


@contextmanager
def _isolated_loop_env(ctx: ShadowContext):
    keys = [
        "DUAL_BRIDGE_ROOT",
        "DUAL_BRIDGE_LOCK",
        "DUAL_BRIDGE_ENDPOINT",
        "DUAL_BRIDGE_REPO_ALLOWLIST",
        "DUAL_BRIDGE_CODEX_BIN",
        "DUAL_BRIDGE_STATE",
    ]
    old_env = {key: os.environ.get(key) for key in keys}
    try:
        os.environ["DUAL_BRIDGE_ROOT"] = str(ctx.bridge_root)
        os.environ["DUAL_BRIDGE_LOCK"] = str(ctx.lock_path)
        os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
        os.environ["DUAL_BRIDGE_REPO_ALLOWLIST"] = ctx.repo
        if ctx.codex_bin:
            os.environ["DUAL_BRIDGE_CODEX_BIN"] = ctx.codex_bin
        else:
            os.environ.pop("DUAL_BRIDGE_CODEX_BIN", None)
        # loop_driver._state_dir() reads DUAL_BRIDGE_STATE lazily, so isolating
        # the state dir is now just another env override (same as ROOT/LOCK).
        os.environ["DUAL_BRIDGE_STATE"] = str(ctx.state_dir)
        yield
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _auto_accept_result(task_id: str) -> None:
    """Local deterministic reviewer for hermetic shadow runs."""
    lane = bc.send_lane()
    fm = {
        "created": bc.now_iso(),
        "from": "codex@shadow-reviewer",
        "to": "claude@laptop-a",
        "status": "done",
        "task_id": task_id,
        "kind": "review",
        "verdict": "accepted",
        "verdict_reason": "shadow auto-accept",
    }
    body = "## Antwort\nshadow auto-accept\nVERDICT: accepted\n"
    bc.write_text_utf8(
        bc.lane_inbox(lane) / f"result-{task_id}.md",
        bc.build_document(fm, body),
    )


def _run_git(workdir: Path | None, *args: str) -> subprocess.CompletedProcess:
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git not found on PATH")
    cmd = [git]
    if workdir is not None:
        cmd += ["-C", str(workdir)]
    cmd += list(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        env=bc.safe_subprocess_env(),
        creationflags=_NO_WINDOW,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_work_root() -> Path:
    return DEFAULT_SHADOW_ROOT / bc.make_task_id()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one goal-loop seed twice and print only the result diff.")
    parser.add_argument("--seed-file", required=True,
                        help="Goal-loop seed markdown file.")
    parser.add_argument("--source-repo", default=str(_repo_root()),
                        help="Local repo to clone into per-run throwaway origins.")
    parser.add_argument("--work-root", default=None,
                        help="Run root. Default: scripts/state/_shadow_runs/<stamp>.")
    parser.add_argument("--base-branch", default="main")
    parser.add_argument("--max-rounds", type=int, default=4)
    parser.add_argument("--round-timeout", type=int, default=600)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--loop-id", default=None,
                        help="Optional fixed loop id. Default derives from seed/config.")
    parser.add_argument("--review-mode", choices=["auto-accept", "external"],
                        default="auto-accept",
                        help="auto-accept is hermetic; external waits for a real reviewer.")
    parser.add_argument("--codex-bin", default=None,
                        help="Optional Codex binary/shim for the build runner.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, run_once_fn: RunOnceFn | None = None,
         repo_factory: RepoFactory | None = None, stdout=None) -> int:
    bc.ensure_utf8_runtime()
    args = _parse_args(argv)
    stdout = stdout or sys.stdout
    seed_text = Path(args.seed_file).read_text(encoding="utf-8")
    work_root = Path(args.work_root) if args.work_root else _default_work_root()

    result = run_shadow_pair(
        seed_text=seed_text,
        source_repo=Path(args.source_repo),
        work_root=work_root,
        base_branch=args.base_branch,
        max_rounds=args.max_rounds,
        round_timeout=args.round_timeout,
        interval=args.interval,
        loop_id=args.loop_id,
        review_mode=args.review_mode,
        codex_bin=args.codex_bin,
        repo_factory=repo_factory,
        run_once_fn=run_once_fn,
    )
    diff = render_diff(result)
    if diff:
        stdout.write(diff)
    return 1 if diff else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
