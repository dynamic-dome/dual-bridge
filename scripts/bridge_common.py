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
import socket
import sys
import uuid as _uuid
from pathlib import Path

# --- Windows UTF-8 hardening (global CLAUDE.md MCP/Windows convention) -------
# Keep umlauts intact in stdout regardless of the host code page.
def ensure_utf8_runtime() -> None:
    """Reconfigure this process' stdout/stderr to UTF-8 (idempotent, never raises).

    Centralizes the scattered ``sys.stdout.reconfigure(encoding="utf-8")``
    try/except blocks. Safe to call repeatedly: reconfigure is a no-op once the
    stream already speaks UTF-8, and any environment without a reconfigure()
    (redirected/pipe stream) is swallowed silently.
    """
    for stream in (sys.stdout, sys.stderr):
        try:  # pragma: no cover - environment dependent
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


ensure_utf8_runtime()


# --- Child-process environment hardening (QW2 + QW3) -------------------------
# Allowlist-only env for spawned children. Closes cross-key leaks
# (OpenAI<->Anthropic) systematically instead of denylisting one key at a time,
# and pins PYTHONUTF8=1 so codex/claude/git run UTF-8 regardless of the host
# code page.
#
# APPDATA + LOCALAPPDATA are MANDATORY (user requirement): Claude/Codex/Node CLIs
# look there for their auth/config data. Without them the subprocess is cleanly
# built but runs UNAUTHENTICATED (P006/P007: mechanics != contract fidelity — the
# exact trap a pure build test would not reveal).
_ALLOW_EXACT = {
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "TEMP", "TMP", "HOME", "HOMEDRIVE",
    "HOMEPATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "COMSPEC",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "PATHEXT",
    # Q4 (Codex-Verifier): git over SSH-agent / HTTPS-proxy / corporate cert
    # would silently break without these. Harmless when unset on this machine.
    # http_proxy/https_proxy (lowercase, Unix-style) normalise to the same upper
    # name via k.upper(), so they are covered by these entries.
    "SSH_AUTH_SOCK", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
}
# Case-insensitive prefix match. PATH covers PATH/PATHEXT-casing variants;
# PYTHON covers PYTHONUTF8/PYTHONPATH/...; GIT_/LANG/LC_ keep git + locale sane.
# DUAL_BRIDGE_ lets the bridge's own config reach child processes (loop_driver,
# codex_adapter): a DUAL_BRIDGE_CONFIG path-override or DUAL_BRIDGE_CODEX_TIMEOUT
# set in the parent must be honoured by the subprocess, not silently dropped
# (Codex-Verifier L3 2026-06-07). The _SECRET_SUBSTR denylist below still strips
# any secret-smelling DUAL_BRIDGE_* (e.g. DUAL_BRIDGE_TG_TOKEN -> 'TOKEN').
_ALLOW_PREFIX = ("PATH", "PYTHON", "GIT_", "LANG", "LC_", "DUAL_BRIDGE_")
# Q1 (Codex-Verifier): the broad prefixes (GIT_, PATH, PYTHON) could let a
# secret through (e.g. GIT_TOKEN, PATH_SECRET). A final denylist substring pass
# drops anything that smells like a credential, regardless of how it matched.
_SECRET_SUBSTR = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL",
                  "APIKEY", "API_KEY", "PRIVATE_KEY", "ACCESS_KEY",
                  # Q1 round 2 (Codex-Verifier): bare KEY + OAuth/bearer/PAT so
                  # GIT_BEARER, GIT_OAUTH, PYTHON_KEY, *_PAT cannot slip through.
                  # NB: use "AUTH_" / "AUTHORIZATION" (not bare "AUTH") so the
                  # legitimate SSH_AUTH_SOCK transport var is NOT killed.
                  "BEARER", "OAUTH", "_KEY", "AUTH_", "AUTHORIZATION", "_PAT",
                  # Q1 round 3 (Codex-Verifier): GIT_HTTP_EXTRAHEADER can carry an
                  # "Authorization: Bearer ..." credential with none of the above
                  # substrings -> block any *_HEADER / EXTRAHEADER var too.
                  "EXTRAHEADER", "HEADER")
# Allowlisted transport vars that must survive the secret denylist even though
# their name brushes a secret substring (SSH_AUTH_SOCK contains 'AUTH').
_SECRET_EXCEPT = frozenset({"SSH_AUTH_SOCK"})


def safe_subprocess_env(extra: dict | None = None) -> dict:
    """Build an allowlist-only environment dict for a child process.

    Keeps only the explicitly allowlisted vars (exact names + prefixes), drops
    anything that looks like a secret even if it matched a broad prefix (Q1),
    forces PYTHONUTF8=1, and as belt-and-braces pops any Anthropic key/token.
    ``extra`` is overlaid last (override).
    """
    base = {
        k: v for k, v in os.environ.items()
        if k.upper() in _ALLOW_EXACT or k.upper().startswith(_ALLOW_PREFIX)
    }
    # Q1: secret-substring denylist beats the broad allowlist prefixes.
    for k in list(base):
        if k.upper() in _SECRET_EXCEPT:
            continue  # explicit transport var (e.g. SSH_AUTH_SOCK) — keep it
        if any(s in k.upper() for s in _SECRET_SUBSTR):
            del base[k]
    base["PYTHONUTF8"] = "1"
    # belt+braces: the Anthropic vars must never reach a subscription-login child.
    base.pop("ANTHROPIC_API_KEY", None)
    base.pop("ANTHROPIC_AUTH_TOKEN", None)
    if extra:
        base.update(extra)
    return base


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


# --- Central config.json (single editable source of truth for tunables) -----
# All the bridge's tunable knobs (timeouts, intervals, max-rounds, schedule
# defaults) are read through config_value(), which applies a strict precedence
# chain so the user can change behaviour by editing ONE file:
#
#     explicit CLI arg  >  env var  >  config.json  >  hardcoded fallback
#
# CLI args sit above this function (they pass the value straight into the
# function parameter and never reach config_value). config.json lives at the
# repo root (next to README.md), is plain JSON (no deps), and is OPTIONAL:
# a missing or malformed file fails soft to {} so the bridge never crashes on a
# typo in a config the user is hand-editing.
import json as _json

_config_cache: dict | None = None
_config_cache_path: str | None = None


def default_config_path() -> Path:
    """Path to config.json. Honors DUAL_BRIDGE_CONFIG override (used by tests and
    for pointing at an alternate config), else <repo-root>/config.json — the repo
    root is the parent of this scripts/ directory."""
    override = os.environ.get("DUAL_BRIDGE_CONFIG")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config.json"


def bridge_config(use_cache: bool = True) -> dict:
    """Load and return config.json as a dict (flat key -> value).

    Fail-soft: a missing file or invalid JSON returns {} rather than raising —
    the config is user-hand-edited, so a typo must degrade to hardcoded
    fallbacks, not break the bridge. Cached per resolved path; pass
    use_cache=False to force a fresh read after editing the file in a long-lived
    process (the manual-edit-and-reload path)."""
    global _config_cache, _config_cache_path
    # Cache key is the *resolved* absolute path so a relative DUAL_BRIDGE_CONFIG
    # or a cwd change can neither false-miss (same file, two keys) nor false-hit
    # (two relative paths, one key). (Codex-Verifier L2 2026-06-07.)
    path = default_config_path().resolve()
    key = str(path)
    if use_cache and _config_cache is not None and _config_cache_path == key:
        return _config_cache
    try:
        data = _json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    _config_cache = data
    _config_cache_path = key
    return data


def config_value(key: str, env_var: str | None, fallback, cast=str):
    """Resolve a tunable via the precedence chain env > config.json > fallback.

    - ``env_var``: the DUAL_BRIDGE_* override name, or None if the knob has no
      env override.
    - ``cast``: applied to env and config values (e.g. int). A value that fails
      to cast is treated as absent and the next rung is tried, ending at the
      already-typed ``fallback`` — a garbage hand-edit degrades, never crashes.
    """
    if env_var is not None:
        raw = os.environ.get(env_var)
        if raw is not None and raw != "":
            try:
                return cast(raw)
            except (TypeError, ValueError):
                pass  # fall through to config.json
    cfg = bridge_config()
    if key in cfg:
        try:
            return cast(cfg[key])
        except (TypeError, ValueError):
            pass  # fall through to fallback
    return fallback


# --- Endpoints & lanes -------------------------------------------------------
# Two endpoints, one human -> a static dict is enough (no config file/YAML).
# Each endpoint sends into the outbox of its OUTGOING lane and polls the outbox
# of every lane where it is the RECEIVER. Direction-separated lanes mean two
# active pollers (A and B) never share a claim pool -> the documented
# cross-device rename race (os.rename is only LOCAL-atomic) cannot occur.
ENDPOINTS = {
    "claude@laptop-a": {"sends_on": "A-to-B", "receives_on": ["B-to-A"]},
    "codex@laptop-b":  {"sends_on": "B-to-A", "receives_on": ["A-to-B"]},
}
DEFAULT_LANE = "A-to-B"  # legacy / Stage-1 direction

# Hostname -> full endpoint string. The endpoint encodes the MACHINE (a/b), which
# is all that determines lane direction; the claude@/codex@ prefix is cosmetic
# (the real adapter comes from the task's `adapter:` field). Auto-detecting from
# the hostname removes the recurring role/agent confusion and the hard
# claude@laptop-a default that made the suite depend on a machine's setx value.
# NOTE: gethostname() returns mixed case ("DoMe-Dynamics") while the Drive claims
# carry "DOME-DYNAMICS" -> keys are uppercase and matched via host.upper().
HOSTNAME_TO_ENDPOINT = {
    "DOME-DYNAMICS":    "codex@laptop-b",
    "K472HEXXZACKBUUM": "claude@laptop-a",
}


def this_endpoint() -> str:
    """Who am I. Resolution order: explicit DUAL_BRIDGE_ENDPOINT override ->
    hostname auto-detection (case-insensitive) -> ValueError naming the host.
    No silent claude@laptop-a fallback: an unknown host must be configured, not
    guessed (the wrong-default drift cost real diagnosis time, Wiki-TODO P2)."""
    override = os.environ.get("DUAL_BRIDGE_ENDPOINT")
    if override:
        return override
    host = socket.gethostname()
    mapped = HOSTNAME_TO_ENDPOINT.get(host.upper())
    if mapped:
        return mapped
    raise ValueError(
        f"Unbekannter Host {host!r} und kein DUAL_BRIDGE_ENDPOINT gesetzt. "
        f"Bekannte Hosts: {', '.join(HOSTNAME_TO_ENDPOINT)}. "
        f"Setze die Identitaet explizit, z.B.: "
        f"setx DUAL_BRIDGE_ENDPOINT \"codex@laptop-b\""
    )


def lane_root(lane: str) -> Path:
    return bridge_root() / f"lane-{lane}"


def lane_outbox(lane: str) -> Path:
    return lane_root(lane) / "outbox"


def lane_inbox(lane: str) -> Path:
    return lane_root(lane) / "inbox"


def lane_processed(lane: str) -> Path:
    return lane_root(lane) / "_processed"


def lane_errors(lane: str) -> Path:
    # Quarantine for malformed/hostile task files — kept OUT of ensure_dirs()
    # and separate from _processed/ so it is visibly not-normal. Created lazily
    # by the poller (handoff_poll) when something actually needs quarantining.
    return lane_root(lane) / "_errors"


def _endpoint_cfg(endpoint: str | None) -> dict:
    ep = endpoint or this_endpoint()
    try:
        return ENDPOINTS[ep]
    except KeyError:
        raise ValueError(
            f"Unbekannter Endpoint {ep!r}. Erlaubt: {', '.join(ENDPOINTS)}"
        ) from None


def send_lane(endpoint: str | None = None) -> str:
    return _endpoint_cfg(endpoint)["sends_on"]


def receive_lanes(endpoint: str | None = None) -> list[str]:
    return list(_endpoint_cfg(endpoint)["receives_on"])


# --- Legacy helpers (default lane) — keep Stage-0/1 tests green --------------
def outbox_dir() -> Path:
    return lane_outbox(DEFAULT_LANE)


def inbox_dir() -> Path:
    return lane_inbox(DEFAULT_LANE)


def processed_dir() -> Path:
    return lane_processed(DEFAULT_LANE)


def errors_dir() -> Path:
    return lane_errors(DEFAULT_LANE)


def ensure_dirs() -> None:
    """Create outbox/inbox/_processed for every known lane (idempotent)."""
    for lane in {DEFAULT_LANE, *(_e["sends_on"] for _e in ENDPOINTS.values())}:
        for d in (lane_outbox(lane), lane_inbox(lane), lane_processed(lane)):
            d.mkdir(parents=True, exist_ok=True)


# --- Time / id helpers -------------------------------------------------------
def now_iso() -> str:
    """Local wall-clock timestamp, second precision, no microseconds."""
    return _dt.datetime.now().replace(microsecond=0).isoformat()


_id_counter = _itertools.count()

import re as _re

# A legitimate make_task_id() is YYYYMMDD-HHMMSS-<micros>-<seq>-<rand>:
#   20260531-000157-681311-0-1f1f  (date-time-micros-seqhex-randhex)
# Only digits, lowercase hex and hyphens occur. We validate any id read from a
# task file against this exact shape before it reaches a result filename
# (inbox/result-<id>.md) or a git branch name (bridge/task-<id>) — the shared
# Drive folder is an untrusted boundary, so an id with '../', spaces, ';' or
# git-flag prefixes ('--force') must never be honoured.
_TASK_ID_RE = _re.compile(
    r"^[0-9]{8}-[0-9]{6}-[0-9]{6}-[0-9a-f]+-[0-9a-f]{4}$"
)


def is_valid_task_id(task_id: str) -> bool:
    """True only for ids in the exact make_task_id() shape. Rejects empty,
    over-long, traversal, and metacharacter-bearing ids."""
    if not task_id or len(task_id) > 64:
        return False
    return bool(_TASK_ID_RE.match(task_id))


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
        # Another claim exists → we lost. Surrender ours so the winner's claim
        # stands and we leave NO orphan behind. Prefer putting the task back to
        # an open task-<id>.md (so it survives even if the winner later fails);
        # if an open task already exists, just drop our duplicate claim.
        _surrender_claim(claimed_path, task_path)
        return None
    return claimed_path


def _surrender_claim(claimed_path: Path, original_path: Path) -> None:
    """Loser cleanup for claim_task: rename our claim back to the open task name
    if that slot is free, else delete our claim. Never raises (best-effort)."""
    try:
        if not original_path.exists():
            os.rename(claimed_path, original_path)
            return
    except OSError:
        pass  # fall through to unlink
    try:
        if claimed_path.exists():
            claimed_path.unlink()
    except OSError:
        pass


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


def _pid_exists(pid: int) -> bool:
    """True if a process with `pid` currently exists on this OS (existence only)."""
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


def _pid_cmdline(pid: int) -> str:
    """Best-effort command line of `pid`, or "" if it can't be determined.

    Windows: tasklist carries no cmdline -> Get-CimInstance Win32_Process. POSIX:
    /proc/<pid>/cmdline (NUL-separated). An empty return means "unknown" and the
    caller treats it conservatively (see _pid_alive). Never raises."""
    if pid <= 0:
        return ""
    if os.name == "nt":
        out = _subprocess_run_quiet([
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}')"
            f".CommandLine",
        ])
        return out.strip()
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _pid_alive(pid: int, must_match: str | None = None) -> bool:
    """True if `pid` is a live process. With must_match, additionally require the
    process command line to contain that marker (case-insensitive) -- this is the
    anti-PID-recycling guard (L11): a recycled svchost holding our old pid has a
    different cmdline and is correctly seen as stale.

    Fail-safe: if the pid exists but its cmdline can't be read (empty), assume
    alive. Never false-negative a real running poller into a double-claim."""
    if not _pid_exists(pid):
        return False
    if must_match is None:
        return True
    cmdline = _pid_cmdline(pid)
    if not cmdline:
        return True  # conservative: exists but cmdline unknown -> assume ours
    return must_match.lower() in cmdline.lower()


def _subprocess_run_quiet(cmd: list[str]) -> str:
    """Run a CMD-internal tool (e.g. `tasklist`) and return stdout.

    Decodes with encoding='oem' (User-Ergänzung, Roadmap-Dossier 4): Windows
    `tasklist` emits the OEM code page (e.g. cp850 on a German locale), which is
    NOT valid UTF-8. `oem` is the lossless OEM code page (CPython #105312) and
    decodes the full output faithfully, where a utf-8+errors='replace' decode
    would only be safe for the bare pid digits and corrupt everything else."""
    import subprocess
    # CREATE_NO_WINDOW: die ops-Konsole pollt /api/ops/status im Sekundentakt und
    # loest dabei diese PID-Checks aus (tasklist via _pid_exists, powershell
    # Get-CimInstance via _pid_cmdline — je Endpoint A/B + Worker-Heartbeat).
    # Der DCO-uvicorn laeuft fensterlos (pythonw), also wuerde Windows fuer jedes
    # dieser Konsolen-Kinder ein NEUES Fenster aufmachen -> bei jedem Konsolen-
    # Update blitzen mehrere PowerShell-Fenster auf. Das Flag unterdrueckt sie.
    # getattr(..., 0): CREATE_NO_WINDOW existiert nur auf Windows; 0 ist auf POSIX
    # der no-op-Default (dieser Pfad wird dort ohnehin nie erreicht).
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="oem",
                            stdin=subprocess.DEVNULL,
                            creationflags=no_window)
        return cp.stdout or ""
    except (OSError, ValueError, LookupError):
        # LookupError: the 'oem' codec is Windows-only; on a non-Windows host
        # (where this path is never reached anyway) the lookup would fail. Stay
        # graceful rather than raise. (Codex-Verifier Q5.)
        return ""


def acquire_singleton_lock(lock_path: Path | None = None,
                           must_match: str | None = None) -> bool:
    """Try to take the local poller lock. Returns True if acquired (and registers
    an atexit release), False if a LIVE poller already holds it. A stale lock
    (file present but its pid is dead) is taken over.

    must_match: a command-line marker that the lock holder's process must carry
    to count as live (passed through to _pid_alive). Each poller passes its own
    script name (e.g. "handoff_poll", "job_poll", "loop_driver") so a recycled
    foreign pid is correctly seen as stale (L11). None = existence-only (legacy)."""
    lock = lock_path or default_lock_path()
    if lock.exists():
        try:
            first = lock.read_text(encoding="utf-8").splitlines()[0].strip()
            held_pid = int(first)
        except (ValueError, IndexError, OSError):
            held_pid = -1
        if held_pid != os.getpid() and _pid_alive(held_pid, must_match=must_match):
            return False  # a live poller (verified by cmdline) holds it
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
