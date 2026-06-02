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
    """Stage-0 echo: reflect the auftrag back, no LLM."""
    return RunnerResult(
        status="done",
        antwort=(f"{auftrag}\n\n(Echo — Laptop hat den Task gelesen und den "
                 "Auftragstext zurückgespiegelt. Kein LLM.)"),
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
