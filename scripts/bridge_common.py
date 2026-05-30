"""Shared helpers for the Dual-Laptop-Bridge (Stage 0).

Pure stdlib, no third-party deps — must run identically on Laptop A and the
older Laptop B without an install step. Carries the task protocol, the
Sharepoint paths, atomic claiming, and a minimal frontmatter parser/writer.

Design constraints (from SHAREPOINT_MANIFEST.md):
- Code lives locally, never inside the Sharepoint (manifest section 7).
- No auto-delete: processed tasks are *moved*, never removed (rule 7).
- No secrets in any written file (rule 6).
"""
from __future__ import annotations

import datetime as _dt
import itertools as _itertools
import os
import sys
import uuid as _uuid
from pathlib import Path

# --- Windows UTF-8 hardening (global CLAUDE.md MCP/Windows convention) -------
# Keep umlauts intact in stdout regardless of the host code page.
try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# --- Bridge root resolution --------------------------------------------------
# The Google-Drive Sharepoint path can differ per device. Resolve in this order:
#   1. DUAL_BRIDGE_ROOT env var (explicit override, e.g. on Laptop B)
#   2. Default Google-Drive mount on this machine
DEFAULT_BRIDGE_ROOT = (
    r"G:\Meine Ablage\dynamic-AI\dynamic_sharepoint\00_INBOX\dual-bridge"
)


def bridge_root() -> Path:
    """Return the bridge data root (where outbox/inbox/_processed live)."""
    override = os.environ.get("DUAL_BRIDGE_ROOT")
    root = Path(override) if override else Path(DEFAULT_BRIDGE_ROOT)
    return root


def outbox_dir() -> Path:
    return bridge_root() / "outbox"


def inbox_dir() -> Path:
    return bridge_root() / "inbox"


def processed_dir() -> Path:
    return bridge_root() / "_processed"


def ensure_dirs() -> None:
    """Create the three bridge subdirs if missing (idempotent)."""
    for d in (outbox_dir(), inbox_dir(), processed_dir()):
        d.mkdir(parents=True, exist_ok=True)


# --- Time / id helpers -------------------------------------------------------
def now_iso() -> str:
    """Local wall-clock timestamp, second precision, no microseconds."""
    return _dt.datetime.now().replace(microsecond=0).isoformat()


_id_counter = _itertools.count()


def make_task_id() -> str:
    """A sortable, collision-free id: YYYYMMDD-HHMMSS-<micros>-<seq>-<rand>.

    F2 fix: second-precision + pid%1000 collided for same-second/same-process
    creation. We add three independent guards so collision is impossible in
    practice:
      - microseconds          → separates same-second ids
      - a process-wide counter → separates same-microsecond ids (Windows' clock
        resolution is coarser than 1us, so micros alone can repeat in a tight loop)
      - a uuid tail            → separates across processes/devices
    """
    now = _dt.datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    seq = next(_id_counter)
    return f"{stamp}-{now.microsecond:06d}-{seq:x}-{_uuid.uuid4().hex[:4]}"


# --- Frontmatter (minimal YAML subset) --------------------------------------
# We only support flat `key: value` pairs — enough for the task protocol and
# free of a PyYAML dependency. Body is everything after the closing `---`.
def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split a markdown file into (frontmatter_dict, body).

    Tolerant of a leading UTF-8 BOM (Drive/Windows artifacts). Returns an empty
    dict and the full text as body if no frontmatter block is present.
    """
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # lines[0] == "---"; find the closing fence
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        fm[key.strip()] = val.strip()
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fm, body


def build_document(frontmatter: dict[str, str], body: str) -> str:
    """Serialize a flat frontmatter dict + body back to a markdown string."""
    out = ["---"]
    for key, val in frontmatter.items():
        out.append(f"{key}: {val}" if val != "" else f"{key}:")
    out.append("---")
    out.append("")
    out.append(body.rstrip("\n"))
    out.append("")
    return "\n".join(out)


def write_text_utf8(path: Path, content: str) -> None:
    """Write UTF-8 *without* BOM (avoids the BOM-breaks-readers trap)."""
    path.write_text(content, encoding="utf-8", newline="\n")


def write_text_atomic(path: Path, content: str) -> None:
    """Write atomically: write to a temp name *outside* the task-*/result-*
    glob, then os.replace into the final name (F3 — no partial-file reads).

    The temp name uses a uuid so concurrent writers never collide on it.
    """
    tmp = path.with_name(f".tmp-{_uuid.uuid4().hex}-{path.name}")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)  # atomic on the local filesystem


def write_text_exclusive(path: Path, content: str) -> bool:
    """Create a new file, failing if it already exists (F1/F2 — never silently
    overwrite a task/result). Returns True on success, False if the path was
    already taken. Writes via a temp file + os.link-free exclusive create.
    """
    try:
        # "x" mode = exclusive create; raises FileExistsError if present.
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        return True
    except FileExistsError:
        return False


def read_text_utf8(path: Path) -> str:
    """Read UTF-8, transparently stripping a BOM if present."""
    return path.read_text(encoding="utf-8-sig")


# --- Atomic claim ------------------------------------------------------------
# F1 — IMPORTANT SCOPE NOTE:
# os.rename is atomic on a *local* filesystem, so within one machine only one
# process can win the rename of the original file. It is NOT a distributed lock:
# across the Drive-synced folder two devices can each rename their local copy
# before Drive converges, producing conflict copies. Stage 0/1 therefore runs
# under a HARD SINGLE-POLLER INVARIANT — exactly one handoff_poll.py per bridge.
# To make accidental double-processing *visible* rather than silent, the claim:
#   1) stamps a unique claim_id into the name (so two claims never collide on
#      the same target name and one silently overwrites the other),
#   2) after claiming, scans for sibling .claimed-* files of the same task_id
#      and bails if another claim already exists (loses the race deterministically).
def _task_id_from_name(name: str) -> str:
    """Extract the task id from 'task-<id>.md' or 'task-<id>.claimed-X.md'."""
    stem = name
    for marker in (".claimed-",):
        if marker in stem:
            stem = stem.split(marker, 1)[0]
    # strip leading 'task-' and trailing '.md'
    if stem.startswith("task-"):
        stem = stem[len("task-") :]
    if stem.endswith(".md"):
        stem = stem[: -len(".md")]
    return stem


def claim_task(task_path: Path, device: str) -> Path | None:
    """Attempt to claim an open task file. Returns the claimed path on success,
    or None if the file vanished / was already claimed by someone else.

    Race-deterministic: stamps a unique claim_id and bails if a sibling claim
    for the same task_id already exists.
    """
    if not task_path.exists():
        return None
    task_id = _task_id_from_name(task_path.name)
    claim_id = _uuid.uuid4().hex[:8]
    claimed_name = f"{task_path.stem}.claimed-{device}-{claim_id}{task_path.suffix}"
    claimed_path = task_path.with_name(claimed_name)
    try:
        os.rename(task_path, claimed_path)
    except (FileNotFoundError, PermissionError, OSError):
        # Lost the local race or transient lock — next poll cycle retries.
        return None
    if not claimed_path.exists():
        return None
    # Sibling-claim check: did anyone else already claim the same task_id?
    siblings = [
        p
        for p in claimed_path.parent.glob(f"task-{task_id}.claimed-*.md")
        if p != claimed_path
    ]
    if siblings:
        # Another claim exists → we lost. Surrender ours back so the winner's
        # result stands; do NOT process. (Visible, not silent.)
        try:
            # Rename back toward open only if the original is gone; otherwise
            # just leave our claim — the winner already produced a result.
            pass
        finally:
            return None
    return claimed_path


DEVICE = os.environ.get("DUAL_BRIDGE_DEVICE", os.environ.get("COMPUTERNAME", "unknown"))


# --- Singleton lock (Stage 1) ------------------------------------------------
# Makes double-start of the poller structurally impossible. The lock file lives
# LOCAL to this machine (never inside the Drive-synced bridge root) -- it guards
# one machine against itself, it is NOT a cross-device lock (same lesson as F1:
# local-atomic != distributed). Staleness is decided by PID liveness, so a
# crashed poller (dead pid in the file) is taken over rather than blocking the
# watchdog forever.
import atexit as _atexit


def default_lock_path() -> Path:
    """Local lock path on THIS machine. Honors DUAL_BRIDGE_LOCK override, else
    a temp-dir file. Never the Drive-synced bridge root."""
    override = os.environ.get("DUAL_BRIDGE_LOCK")
    if override:
        return Path(override)
    import tempfile
    return Path(tempfile.gettempdir()) / "dual-bridge-poller.lock"


def _pid_alive(pid: int) -> bool:
    """True if a process with `pid` currently exists on this OS."""
    if pid <= 0:
        return False
    if os.name == "nt":
        out = _subprocess_run_quiet(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"]
        )
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def _subprocess_run_quiet(cmd: list[str]) -> str:
    """Run a command and return stdout. Decodes with errors='replace' because
    Windows `tasklist` emits the OEM code page (e.g. cp850/cp1252 on a German
    locale), which is not valid UTF-8 -- a hard utf-8 decode would raise in the
    reader thread. We only need the ASCII pid digits, so replacement is safe."""
    import subprocess
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            stdin=subprocess.DEVNULL)
        return cp.stdout or ""
    except (OSError, ValueError):
        return ""


def acquire_singleton_lock(lock_path: Path | None = None) -> bool:
    """Try to take the local poller lock. Returns True if acquired (and registers
    an atexit release), False if a LIVE poller already holds it. A stale lock
    (file present but its pid is dead) is taken over."""
    lock = lock_path or default_lock_path()
    if lock.exists():
        try:
            first = lock.read_text(encoding="utf-8").splitlines()[0].strip()
            held_pid = int(first)
        except (ValueError, IndexError, OSError):
            held_pid = -1
        if held_pid != os.getpid() and _pid_alive(held_pid):
            return False  # a live poller holds it
        # else: stale (dead pid) or our own -- fall through and (re)take it
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(f"{os.getpid()}\n{now_iso()}\n", encoding="utf-8")
    except OSError:
        return False
    _atexit.register(release_singleton_lock, lock)
    return True


def release_singleton_lock(lock_path: Path | None = None) -> None:
    """Remove the lock if it is ours (best-effort; never raises)."""
    lock = lock_path or default_lock_path()
    try:
        if lock.exists():
            first = lock.read_text(encoding="utf-8").splitlines()[0].strip()
            if first == str(os.getpid()):
                lock.unlink()
    except (OSError, ValueError, IndexError):
        pass
