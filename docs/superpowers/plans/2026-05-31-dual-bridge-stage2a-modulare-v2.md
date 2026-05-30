# Dual-Bridge Stage 2a — Schlanke modulare v2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make direction (A↔B) and model (Codex↔Claude) pure configuration — bidirectional, reversible — without Codex's 4-layer infra (YAGNI for 2 laptops).

**Architecture:** Direction-separated lanes (`lane-A-to-B`/`lane-B-to-A`) make the cross-device claim race structurally impossible. An explicit `adapter` frontmatter field separates model from `kind` intent; a `RUNNERS` dict dispatches to `run_echo`/`run_codex`/`run_claude`. Git-publishing stays inside the codex runner, not the runner contract. Endpoint identity (`DUAL_BRIDGE_ENDPOINT`) drives which lanes a node polls — the same scripts run on A and B.

**Tech Stack:** Python 3 stdlib only (no deps). Test runner: plain `assert` scripts (`python test_*.py`), no pytest. Files live in `scripts/`.

**Reference spec:** `docs/superpowers/specs/2026-05-31-dual-bridge-stage2a-modulare-v2-design.md`

**Baseline before starting:** `test_hardening.py` 10/10, `test_stage1.py` 17/17 (commit `8be392e`). Every task must keep both green.

---

## File Structure

- `scripts/bridge_common.py` (MODIFY) — add endpoint table + lane-aware path resolution; keep `outbox_dir()` etc. as default-lane wrappers for back-compat.
- `scripts/runners.py` (CREATE) — `RunnerResult` dataclass + `run_echo`; `RUNNERS` registry. Pure, bridge-agnostic.
- `scripts/codex_adapter.py` (MODIFY) — adapt `run_codex_task` to the shared signature + `RunnerResult`; add repo-allowlist guard.
- `scripts/claude_adapter.py` (CREATE) — `run_claude` via `claude -p` headless, P006 parsing, no forced git.
- `scripts/handoff_poll.py` (MODIFY) — split `process_one` into claim→route→run→publish; dispatch on `adapter`; lane-aware; `to`-filter.
- `scripts/handoff_write.py` (MODIFY) — `--adapter`, `--to`, endpoint-relative outbox.
- `scripts/handoff_collect.py` (MODIFY) — endpoint-relative inbox.
- `scripts/test_lanes.py` (CREATE) — lane resolution, to-filter, B→A roundtrip, runner dispatch.
- `scripts/test_claude_adapter.py` (CREATE) — `run_claude` P006 parsing against fake CLI.
- `scripts/test_hardening.py`, `scripts/test_stage1.py` (MODIFY only if a back-compat shim requires an env default).

**Decomposition note:** Tasks 1–3 build the new primitives (lanes, runner registry, claude adapter) without touching the live poller — each is independently testable and the existing suites stay green. Task 4 rewires the poller. Tasks 5–6 make the CLI endpoint-relative. Task 7 proves B→A end-to-end. Task 8 updates wiki TODOs (the "A" deliverable).

---

## Task 1: Endpoint table + lane-aware path resolution

**Files:**
- Modify: `scripts/bridge_common.py` (path helpers around lines 46–67)
- Test: `scripts/test_lanes.py` (create)

Back-compat is mandatory: existing tests call `outbox_dir()`/`inbox_dir()`/`processed_dir()`/`errors_dir()` with no lane. Those must keep resolving to a **default lane** so `test_hardening.py` / `test_stage1.py` stay green.

- [ ] **Step 1: Write the failing test**

Create `scripts/test_lanes.py`:

```python
"""Stage 2a lane + routing tests. Pure stdlib + assert:
    python test_lanes.py
Isolated via DUAL_BRIDGE_ROOT -> tmp dir; DUAL_BRIDGE_ENDPOINT sets identity.
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-s2a-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_lane_dirs_resolve_under_lane() -> None:
    _fresh_bridge()
    import bridge_common as bc
    importlib.reload(bc)
    ob = bc.lane_outbox("A-to-B")
    ib = bc.lane_inbox("A-to-B")
    assert ob.name == "outbox" and ob.parent.name == "lane-A-to-B", ob
    assert ib.name == "inbox" and ib.parent.name == "lane-A-to-B", ib
    assert bc.lane_outbox("B-to-A").parent.name == "lane-B-to-A"
    print("  lane OK — lane_outbox/lane_inbox resolve under lane-<dir>/")


def test_default_lane_backcompat() -> None:
    _fresh_bridge()
    import bridge_common as bc
    importlib.reload(bc)
    # The legacy helpers must still work and point at the default lane.
    assert bc.outbox_dir().parent.name.startswith("lane-"), bc.outbox_dir()
    assert bc.outbox_dir().name == "outbox"
    assert bc.inbox_dir().name == "inbox"
    print("  lane OK — legacy outbox_dir/inbox_dir map to the default lane")


def main() -> int:
    print("=== Stage-2a Lane-Tests ===")
    tests = [test_lane_dirs_resolve_under_lane, test_default_lane_backcompat]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_lanes.py`
Expected: FAIL/ERROR — `bridge_common has no attribute 'lane_outbox'`.

- [ ] **Step 3: Write minimal implementation**

In `scripts/bridge_common.py`, add the endpoint table + lane helpers and rewrite the legacy helpers as default-lane wrappers. Replace the block at lines 46–61 (`outbox_dir`…`errors_dir`) with:

```python
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


def this_endpoint() -> str:
    """Who am I. DUAL_BRIDGE_ENDPOINT overrides; default is the A/Claude node."""
    return os.environ.get("DUAL_BRIDGE_ENDPOINT", "claude@laptop-a")


def lane_root(lane: str) -> Path:
    return bridge_root() / f"lane-{lane}"


def lane_outbox(lane: str) -> Path:
    return lane_root(lane) / "outbox"


def lane_inbox(lane: str) -> Path:
    return lane_root(lane) / "inbox"


def lane_processed(lane: str) -> Path:
    return lane_root(lane) / "_processed"


def lane_errors(lane: str) -> Path:
    return lane_root(lane) / "_errors"


def send_lane(endpoint: str | None = None) -> str:
    ep = endpoint or this_endpoint()
    return ENDPOINTS.get(ep, ENDPOINTS["claude@laptop-a"])["sends_on"]


def receive_lanes(endpoint: str | None = None) -> list[str]:
    ep = endpoint or this_endpoint()
    return list(ENDPOINTS.get(ep, ENDPOINTS["claude@laptop-a"])["receives_on"])


# --- Legacy helpers (default lane) — keep Stage-0/1 tests green --------------
def outbox_dir() -> Path:
    return lane_outbox(DEFAULT_LANE)


def inbox_dir() -> Path:
    return lane_inbox(DEFAULT_LANE)


def processed_dir() -> Path:
    return lane_processed(DEFAULT_LANE)


def errors_dir() -> Path:
    return lane_errors(DEFAULT_LANE)
```

Then update `ensure_dirs()` (lines 64–67) to create dirs for ALL lanes:

```python
def ensure_dirs() -> None:
    """Create outbox/inbox/_processed for every known lane (idempotent)."""
    for lane in {DEFAULT_LANE, *(_e["sends_on"] for _e in ENDPOINTS.values())}:
        for d in (lane_outbox(lane), lane_inbox(lane), lane_processed(lane)):
            d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python test_lanes.py`
Expected: PASS — both lane tests green.

- [ ] **Step 5: Run the full existing suites (regression)**

Run: `cd scripts && python test_hardening.py && python test_stage1.py`
Expected: `test_hardening.py` 10/10, `test_stage1.py` 17/17 — still green (legacy helpers map to default lane).

- [ ] **Step 6: Commit**

```bash
git add scripts/bridge_common.py scripts/test_lanes.py
git commit -m "feat(bridge): endpoint table + lane-aware path resolution (default-lane back-compat)"
```

---

## Task 2: RunnerResult + runner registry + run_echo

**Files:**
- Create: `scripts/runners.py`
- Test: `scripts/test_lanes.py` (extend)

This extracts the result type and the echo behaviour into a bridge-agnostic module. `run_codex`/`run_claude` join the registry in Tasks 3 (codex stays in its file, registered here).

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_lanes.py` (before `main`):

```python
def test_runner_result_to_markdown() -> None:
    import runners
    importlib.reload(runners)
    r = runners.RunnerResult(status="done", antwort="hallo welt")
    md = r.to_markdown(task_id="T1", claimed_by="x", claimed_at="now")
    assert "## Quelle" in md and "hallo welt" in md
    err = runners.RunnerResult(status="error", error_text="kaputt")
    assert "## FEHLER" in err.to_markdown(task_id="T2", claimed_by="x", claimed_at="now")
    print("  runner OK — RunnerResult.to_markdown renders done + error")


def test_run_echo() -> None:
    import runners
    importlib.reload(runners)
    r = runners.run_echo(auftrag="spiegel mich", fm={"task_id": "T1"}, workroot=None)
    assert r.status == "done" and "spiegel mich" in r.antwort
    print("  runner OK — run_echo returns done with the auftrag echoed")


def test_registry_has_echo() -> None:
    import runners
    importlib.reload(runners)
    assert "echo" in runners.RUNNERS and callable(runners.RUNNERS["echo"])
    print("  runner OK — RUNNERS registry contains echo")
```

Add these three to the `tests` list in `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_lanes.py`
Expected: ERROR — `No module named 'runners'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/runners.py`:

```python
"""Runner registry for the Dual-Laptop-Bridge (Stage 2a).

A runner is a function (auftrag, fm, workroot) -> RunnerResult. The result type
is shared by all runners; git-publishing is NOT part of the contract (only the
codex runner pushes a branch). Pure stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class RunnerResult:
    status: str                       # "done" | "error"
    antwort: str = ""
    branch: Optional[str] = None
    commit: Optional[str] = None
    changed_files: list = field(default_factory=list)
    error_text: Optional[str] = None
    stderr_excerpt: Optional[str] = None
    note: Optional[str] = None

    def to_markdown(self, task_id: str, claimed_by: str, claimed_at: str) -> str:
        lines = ["## Quelle",
                 f"task_id {task_id}, geclaimt von {claimed_by} um {claimed_at}", ""]
        if self.status == "done":
            lines += ["## Antwort", self.antwort, ""]
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


def run_echo(auftrag: str, fm: dict, workroot: Optional[Path]) -> RunnerResult:
    """Stage-0 echo: reflect the auftrag back, no LLM."""
    return RunnerResult(
        status="done",
        antwort=(f"{auftrag}\n\n(Echo — Laptop hat den Task gelesen und den "
                 "Auftragstext zurückgespiegelt. Kein LLM.)"),
    )


# Populated here for echo; codex/claude register themselves via register_runner
# from their own modules to avoid import cycles with bridge code.
RUNNERS: dict[str, Callable[..., RunnerResult]] = {"echo": run_echo}


def register_runner(name: str, fn: Callable[..., RunnerResult]) -> None:
    RUNNERS[name] = fn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python test_lanes.py`
Expected: PASS — all lane + runner tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/runners.py scripts/test_lanes.py
git commit -m "feat(bridge): RunnerResult + RUNNERS registry + run_echo (git not in contract)"
```

---

## Task 3: Adapt codex runner to shared signature + repo-allowlist

**Files:**
- Modify: `scripts/codex_adapter.py` (`run_codex_task` signature + return type; clone guard)
- Test: `scripts/test_stage1.py` (existing codex tests must stay green)

Goal: `run_codex_task` returns a `RunnerResult` (not `CodexResult`) and is registered as `RUNNERS["codex"]` via a thin wrapper matching `(auftrag, fm, workroot)`. Add a repo-allowlist guard.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_lanes.py` (before `main`, add to list):

```python
def test_codex_registered_and_allowlist() -> None:
    import runners, codex_adapter
    importlib.reload(runners); importlib.reload(codex_adapter)
    assert "codex" in runners.RUNNERS, "codex runner not registered"
    # Allowlist: a repo not on a non-empty allowlist -> error before any clone.
    os.environ["DUAL_BRIDGE_REPO_ALLOWLIST"] = "github.com/dynamic-dome/*"
    try:
        r = runners.RUNNERS["codex"](
            auftrag="x",
            fm={"task_id": "20260531-000000-000000-0-aaaa",
                "repo": "https://evil.example/malware.git", "base_branch": "main"},
            workroot=Path(tempfile.mkdtemp(prefix="cdx-al-")),
        )
    finally:
        del os.environ["DUAL_BRIDGE_REPO_ALLOWLIST"]
    assert r.status == "error" and "allowlist" in (r.error_text or "").lower(), \
        f"expected allowlist rejection, got {r.status}/{r.error_text}"
    print("  codex OK — registered + repo-allowlist rejects non-listed repo before clone")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_lanes.py`
Expected: FAIL — codex not in registry / no allowlist logic yet.

- [ ] **Step 3: Write minimal implementation**

In `scripts/codex_adapter.py`:

(a) Replace the `CodexResult` dataclass (lines 76–84) with an import + alias so existing references keep working:

```python
from runners import RunnerResult, register_runner
CodexResult = RunnerResult  # back-compat alias; existing call sites unchanged
```

Remove the now-duplicate `from dataclasses import dataclass, field` only if unused elsewhere; keep `from pathlib import Path`.

(b) At the very top of `run_codex_task` (after the docstring, before `branch = ...`), add the allowlist guard:

```python
    allow = os.environ.get("DUAL_BRIDGE_REPO_ALLOWLIST", "").strip()
    if allow:
        import fnmatch
        patterns = [p.strip() for p in allow.split(",") if p.strip()]
        if not any(fnmatch.fnmatch(repo, pat) for pat in patterns):
            return CodexResult(status="error",
                               error_text=f"repo nicht in allowlist abgelehnt: {repo}")
```

(c) At the end of the file (module bottom), add the registry wrapper:

```python
def _codex_runner(auftrag: str, fm: dict, workroot):
    """Adapt run_codex_task to the (auftrag, fm, workroot) runner signature."""
    from pathlib import Path as _P
    wr = _P(workroot) if workroot is not None else _P.home() / "dual-bridge-work"
    return run_codex_task(
        auftrag=auftrag,
        repo=fm.get("repo", ""),
        base_branch=fm.get("base_branch", "main"),
        task_id=fm["task_id"],
        workroot=wr,
        codex_bin=os.environ.get("DUAL_BRIDGE_CODEX_BIN") or None,
        timeout=int(os.environ.get("DUAL_BRIDGE_CODEX_TIMEOUT", "600")),
    )


register_runner("codex", _codex_runner)
```

- [ ] **Step 4: Run tests to verify pass + regression**

Run: `cd scripts && python test_lanes.py && python test_stage1.py && python test_hardening.py`
Expected: lane tests incl. codex-allowlist green; `test_stage1.py` 17/17 (CodexResult alias keeps every assertion valid); `test_hardening.py` 10/10.

- [ ] **Step 5: Commit**

```bash
git add scripts/codex_adapter.py scripts/test_lanes.py
git commit -m "feat(bridge): codex runner on shared RunnerResult + repo-allowlist guard"
```

---

## Task 4: Claude runner (claude -p, P006 parsing, no forced git)

**Files:**
- Create: `scripts/claude_adapter.py`
- Test: `scripts/test_claude_adapter.py` (create)

`run_claude` runs `claude -p` headless, parses output robustly per P006 (BOM + event-stream + trailing hook noise), and returns text only (no git branch).

- [ ] **Step 1: Write the failing test**

Create `scripts/test_claude_adapter.py`:

```python
"""run_claude parsing tests (P006 shapes) against a fake claude CLI.
    python test_claude_adapter.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path


def test_parse_event_stream_with_hook_noise() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    # claude -p --output-format json: a JSON array (event stream) with a leading
    # BOM and trailing non-JSON hook noise after the closing bracket (P006).
    raw = ('﻿[{"type":"system"},'
           '{"type":"result","result":"die antwort"}]\n'
           'SessionEnd hook failed: not supported\n')
    assert ca.parse_claude_output(raw) == "die antwort"
    print("  claude OK — event-stream + BOM + trailing hook noise -> result text")


def test_parse_empty_is_empty() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    assert ca.parse_claude_output("﻿   \n") == ""
    print("  claude OK — whitespace/BOM-only -> empty")


def _write_fake_claude(tmp: Path, *, answer: str, exit_code: int = 0) -> str:
    bindir = tmp / "fakebin"; bindir.mkdir(parents=True, exist_ok=True)
    py = bindir / "fake_claude.py"
    py.write_text(
        "import sys\n"
        f"ans = {answer!r}\n"
        f"code = {exit_code}\n"
        "if ans:\n"
        "    sys.stdout.write('\\ufeff[{\"type\":\"result\",\"result\":\"' + ans + '\"}]\\n')\n"
        "    sys.stdout.write('Stop hook not supported\\n')\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    cmd = bindir / "claude.cmd"
    cmd.write_text(f'@echo off\r\npython "{py}" %*\r\n', encoding="utf-8")
    sh = bindir / "claude"
    sh.write_text(f'#!/bin/sh\nexec python "{py}" "$@"\n', encoding="utf-8")
    try:
        os.chmod(sh, 0o755)
    except OSError:
        pass
    return str(bindir / ("claude.cmd" if os.name == "nt" else "claude"))


def test_run_claude_happy() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-s2a-"))
    fake = _write_fake_claude(tmp, answer="erledigt")
    r = ca.run_claude(auftrag="tu was", fm={"task_id": "T1"}, workroot=tmp,
                      claude_bin=fake)
    assert r.status == "done" and "erledigt" in r.antwort
    assert r.branch is None, "claude runner darf KEINEN git-branch erzwingen"
    print("  claude OK — run_claude happy path, text only, no branch")


def test_run_claude_not_found() -> None:
    import claude_adapter as ca
    importlib.reload(ca)
    tmp = Path(tempfile.mkdtemp(prefix="claude-nf-"))
    missing = str(tmp / "no-such-claude.exe")
    r = ca.run_claude("x", {"task_id": "T1"}, tmp, claude_bin=missing)
    assert r.status == "error" and "claude" in (r.error_text or "").lower()
    print("  claude OK — missing binary -> status:error (no raise)")


def main() -> int:
    print("=== Stage-2a Claude-Adapter-Tests ===")
    tests = [test_parse_event_stream_with_hook_noise, test_parse_empty_is_empty,
             test_run_claude_happy, test_run_claude_not_found]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}"); failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}"); failed += 1
    print("=" * 48)
    print(f"{'FEHLER: '+str(failed) if failed else 'Alle'} {len(tests)-failed}/{len(tests)} ok")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_claude_adapter.py`
Expected: ERROR — `No module named 'claude_adapter'`.

- [ ] **Step 3: Write minimal implementation**

Create `scripts/claude_adapter.py`:

```python
"""Claude worker adapter for the Dual-Laptop-Bridge (Stage 2a).

Runs `claude -p` headless and returns a RunnerResult with TEXT only — no git
branch (that is codex-specific). Output parsing follows P006: strip a BOM,
raw_decode the first JSON value (ignoring trailing hook noise), pull the final
type:result event. CLAUDE_CODE_DISABLE_HOOKS=1 + stdin=DEVNULL at the source.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from runners import RunnerResult, register_runner

try:  # pragma: no cover - environment dependent
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def parse_claude_output(raw: str) -> str:
    """P006: BOM + event-stream + trailing hook noise tolerant. Returns "" if empty."""
    if raw is None:
        return ""
    text = raw.lstrip("﻿").strip()
    if not text:
        return ""
    if text[0] in "{[":
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            value = None
        if value is not None:
            return _answer_from_json(value).strip()
    return text


def _answer_from_json(value: object) -> str:
    if isinstance(value, list):
        for item in reversed(value):
            if isinstance(item, dict) and item.get("type") == "result":
                r = item.get("result")
                if isinstance(r, str) and r.strip():
                    return r
        for item in reversed(value):
            if isinstance(item, dict):
                for key in ("result", "message", "text", "content"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        return v
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        for key in ("result", "answer", "message", "text", "content"):
            v = value.get(key)
            if isinstance(v, str) and v.strip():
                return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def run_claude(auftrag: str, fm: dict, workroot, claude_bin: Optional[str] = None,
               timeout: int = 600) -> RunnerResult:
    """Run one task via `claude -p`. Text only; never raises (spec contract)."""
    exe = claude_bin or os.environ.get("DUAL_BRIDGE_CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        return RunnerResult(status="error",
                            error_text="claude nicht gefunden — installiert/im PATH?")
    cwd = str(workroot) if workroot is not None else None
    env = dict(os.environ)
    env["CLAUDE_CODE_DISABLE_HOOKS"] = "1"
    cmd = [exe, "-p", "--output-format", "json", auftrag]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", stdin=subprocess.DEVNULL,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(status="error", error_text=f"claude timeout nach {timeout}s",
                            stderr_excerpt=_tail(getattr(exc, "stderr", None)))
    except (FileNotFoundError, OSError) as exc:
        return RunnerResult(status="error",
                            error_text=f"claude nicht ausführbar ({exe}): {exc}")
    if proc.returncode != 0:
        return RunnerResult(status="error", error_text=f"claude exit {proc.returncode}",
                            stderr_excerpt=_tail(proc.stderr))
    antwort = parse_claude_output(proc.stdout)
    if not antwort:
        return RunnerResult(status="error", error_text="claude: leere Antwort",
                            stderr_excerpt=_tail(proc.stderr))
    return RunnerResult(status="done", antwort=antwort)


def _tail(text: Optional[str], limit: int = 2000) -> Optional[str]:
    if not text:
        return None
    return text[-limit:]


register_runner("claude", run_claude)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts && python test_claude_adapter.py`
Expected: PASS — 4/4 claude tests green.

- [ ] **Step 5: Commit**

```bash
git add scripts/claude_adapter.py scripts/test_claude_adapter.py
git commit -m "feat(bridge): claude -p runner with P006 parsing, text-only (no forced git)"
```

---

## Task 5: Rewire poller — claim→route→run→publish, dispatch on adapter, lane-aware

**Files:**
- Modify: `scripts/handoff_poll.py` (`process_one` 37–122, `poll_once` 225–...)
- Test: `scripts/test_lanes.py` (extend with dispatch + to-filter)

Replace the inline codex/echo if-branch in `process_one` with a registry dispatch on `adapter`, validate `to`, and make the poller iterate the receive-lanes of `this_endpoint()`.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_lanes.py` (before `main`, add to list):

```python
def test_poll_dispatches_on_adapter_echo() -> None:
    _fresh_bridge("claude@laptop-a")  # A receives on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nspiegel\n"))
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert rfm["status"] == "done" and "spiegel" in rbody
    print("  poll OK — adapter:echo dispatched via registry, result in B-to-A inbox")


def test_poll_to_filter_skips_foreign() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "x@y", "to": "codex@laptop-b",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "echo",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))
    assert hp.process_one(task, lane="B-to-A") is False, "fremder to muss übersprungen werden"
    print("  poll OK — to-filter skips task addressed to another endpoint")


def test_poll_unknown_adapter_errors() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b", "to": "claude@laptop-a",
          "status": "open", "task_id": task_id, "kind": "research", "adapter": "bogus",
          "claimed_by": "", "claimed_at": ""}
    task = bc.lane_outbox("B-to-A") / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))
    hp.process_one(task, lane="B-to-A")
    rfm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{task_id}.md"))
    assert rfm["status"] == "error", "unbekannter adapter muss status:error liefern"
    print("  poll OK — unknown adapter -> status:error, no crash")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_lanes.py`
Expected: FAIL — `process_one()` has no `lane` kwarg / no adapter dispatch.

- [ ] **Step 3: Write minimal implementation**

In `scripts/handoff_poll.py`:

(a) Replace the codex/echo config block (lines 22–29) — drop `LLM_KINDS`, keep workroot:

```python
import runners  # noqa: F401 -- registers echo
import codex_adapter  # noqa: F401 -- registers codex
import claude_adapter  # noqa: F401 -- registers claude

CODEX_WORKROOT = bc.Path(
    os.environ.get("DUAL_BRIDGE_WORKROOT") or (bc.Path.home() / "dual-bridge-work")
)
```

(Delete the old `import codex_adapter as ca`, `CODEX_BIN`, `CODEX_TIMEOUT`, `LLM_KINDS` lines.)

(b) Rewrite `process_one` to take a `lane` and dispatch on `adapter`. Replace lines 37–122 with:

```python
def process_one(task_path: bc.Path, lane: str) -> bool:
    """Claim + route + run + publish a single task within `lane`. Returns True
    if a result was written."""
    fm, body = bc.parse_frontmatter(bc.read_text_utf8(task_path))
    if fm.get("status") != "open":
        return False

    task_id = fm.get("task_id", task_path.stem.replace("task-", ""))
    if not bc.is_valid_task_id(task_id):
        print(f"[{lane}] Task {task_path.name} hat ungültige task_id {task_id!r} — übersprungen.")
        return False

    # to-filter: only process tasks addressed to me (belt-and-suspenders on top
    # of lane separation). A task with no `to` is treated as legacy/for-me.
    to = fm.get("to", "")
    if to and to != bc.this_endpoint():
        return False

    claimed_path = bc.claim_task(task_path, bc.DEVICE)
    if claimed_path is None:
        print(f"[{lane}] Konnte {task_path.name} nicht claimen — übersprungen.")
        return False

    fm, body = bc.parse_frontmatter(bc.read_text_utf8(claimed_path))
    fm["claimed_by"] = f"{bc.this_endpoint()}@{bc.DEVICE}"
    fm["claimed_at"] = bc.now_iso()

    auftrag = _extract_section(body, "## Auftrag") or body.strip()
    adapter = fm.get("adapter", "echo")
    runner = runners.RUNNERS.get(adapter)
    if runner is None:
        result = runners.RunnerResult(status="error",
                                      error_text=f"unbekannter adapter: {adapter!r}")
    else:
        try:
            result = runner(auftrag=auftrag, fm=fm, workroot=CODEX_WORKROOT)
        except Exception as exc:  # noqa: BLE001 -- a runner must never crash the poller
            result = runners.RunnerResult(status="error",
                                          error_text=f"{adapter} runner crash: {type(exc).__name__}: {exc}")

    fm["status"] = result.status
    extra_fm = {}
    if result.branch:
        extra_fm["branch"] = result.branch
    if result.commit:
        extra_fm["commit"] = result.commit
    result_fm = {
        "created": bc.now_iso(),
        "agent": fm["claimed_by"],
        "from": bc.this_endpoint(),
        "to": fm.get("from", ""),
        "purpose": "handoff",
        "status": result.status,
        "task_id": task_id,
        "kind": fm.get("kind", "echo"),
        "adapter": adapter,
        "replies_to": f"task-{task_id}.md",
        **extra_fm,
    }
    result_body = result.to_markdown(task_id, fm["claimed_by"], fm["claimed_at"])
    result_path = bc.lane_inbox(lane) / f"result-{task_id}.md"
    if not bc.write_text_exclusive(result_path, bc.build_document(result_fm, result_body)):
        print(f"[{lane}] Result für {task_id} existiert bereits — anderer Claim gewann.")
        _archive_claimed(claimed_path, fm, body, lane)
        return False

    bc.write_text_atomic(claimed_path, bc.build_document(fm, body))
    _archive_claimed(claimed_path, fm, body, lane)
    print(f"[{lane}] Verarbeitet: {task_id} → inbox/{result_path.name}")
    return True
```

(c) `_archive_claimed`, `_requeue_claimed`, `_quarantine_claimed` gain a `lane` param and use `bc.lane_processed(lane)` / `bc.lane_errors(lane)` / `bc.lane_outbox(lane)` instead of the legacy dirs. Update their signatures and bodies accordingly (replace `bc.processed_dir()` → `bc.lane_processed(lane)`, `bc.errors_dir()` → `bc.lane_errors(lane)`, `bc.outbox_dir()` → `bc.lane_outbox(lane)`, `bc.inbox_dir()` → `bc.lane_inbox(lane)`).

(d) Rewrite `poll_once` to iterate the receive-lanes of `this_endpoint()`:

```python
def poll_once() -> int:
    bc.ensure_dirs()
    count = 0
    for lane in bc.receive_lanes():
        count += _poll_lane(lane)
    return count


def _poll_lane(lane: str) -> int:
    count = 0
    # Recovery loop (P0 + F4 + injection-guard) — operate within this lane.
    for stranded in sorted(bc.lane_outbox(lane).glob("task-*.claimed-*.md")):
        if _is_conflict_copy(stranded.name):
            continue
        fm, body = bc.parse_frontmatter(bc.read_text_utf8(stranded))
        task_id = fm.get("task_id", bc._task_id_from_name(stranded.name))
        if not bc.is_valid_task_id(task_id):
            if _quarantine_claimed(stranded, lane):
                print(f"[{lane}] Stranded-Claim {stranded.name} ungültige task_id → _errors/.")
            continue
        has_result = (bc.lane_inbox(lane) / f"result-{task_id}.md").exists()
        if fm.get("status") in ("done", "error") and has_result:
            if _archive_claimed(stranded, fm, body, lane):
                print(f"[{lane}] Nachgeholt archiviert: {stranded.name}")
        else:
            if _requeue_claimed(stranded, fm, body, task_id, lane):
                print(f"[{lane}] P0-Recovery: {stranded.name} → requeued (open).")
    for task_path in sorted(bc.lane_outbox(lane).glob("task-*.md")):
        if ".claimed-" in task_path.name or _is_conflict_copy(task_path.name):
            continue
        try:
            if process_one(task_path, lane):
                count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[{lane}] Task {task_path.name} warf {type(exc).__name__}: {exc} — übersprungen.")
    return count
```

Note: `_requeue_claimed` writes back to `bc.lane_outbox(lane) / f"task-{task_id}.md"`.

- [ ] **Step 4: Run tests to verify pass + regression**

Run: `cd scripts && python test_lanes.py && python test_claude_adapter.py`
Expected: lane dispatch + to-filter + unknown-adapter tests green.

The legacy suites call `process_one(task)` / `poll_once()` with the default lane. Update those two suites' calls minimally:
- In `test_hardening.py` and `test_stage1.py`, calls to `hp.process_one(task)` become `hp.process_one(task, lane=bc.DEFAULT_LANE)`, and tasks are written under `bc.lane_outbox(bc.DEFAULT_LANE)` (the legacy `bc.outbox_dir()` already maps there, so existing writes are fine). Stranded-claim tests already use `bc.outbox_dir()` = default lane → unchanged.

Run: `cd scripts && python test_hardening.py && python test_stage1.py`
Expected: 10/10 and 17/17 after the `lane=` argument is threaded through.

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff_poll.py scripts/test_lanes.py scripts/test_hardening.py scripts/test_stage1.py
git commit -m "feat(bridge): poller dispatches on adapter, lane-aware claim→route→run→publish + to-filter"
```

---

## Task 6: Endpoint-relative writer + collector CLI

**Files:**
- Modify: `scripts/handoff_write.py` (add `--adapter`, `--to`; write to send-lane outbox)
- Modify: `scripts/handoff_collect.py` (collect from receive-lane inboxes)
- Test: `scripts/test_lanes.py` (extend: writer puts task in send-lane with adapter/to)

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_lanes.py` (before `main`, add to list):

```python
def test_writer_uses_send_lane_and_adapter() -> None:
    _fresh_bridge("codex@laptop-b")  # B sends on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    rc = hw.main(["bau das feature", "--kind", "implement", "--adapter", "claude"])
    assert rc == 0
    tasks = list(bc.lane_outbox("B-to-A").glob("task-*.md"))
    assert len(tasks) == 1, f"task not in B-to-A send lane: {tasks}"
    fm, _ = bc.parse_frontmatter(bc.read_text_utf8(tasks[0]))
    assert fm["adapter"] == "claude"
    assert fm["from"] == "codex@laptop-b" and fm["to"] == "claude@laptop-a"
    print("  write OK — task in send-lane outbox with adapter + from/to set")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts && python test_lanes.py`
Expected: FAIL — `--adapter` unknown / task not in B-to-A lane.

- [ ] **Step 3: Write minimal implementation**

In `scripts/handoff_write.py`:

(a) Add args after `--base-branch` (line 39):

```python
    parser.add_argument("--adapter", default="echo",
                        choices=["echo", "codex", "claude"],
                        help="Which runner the receiver should use.")
    parser.add_argument("--to", default="",
                        help="Target endpoint (default: the peer of my endpoint).")
```

(b) Replace the frontmatter + out_path block (lines 42–70) so it is endpoint-relative:

```python
    bc.ensure_dirs()
    lane = bc.send_lane()
    me = bc.this_endpoint()
    # default `to` = the receiver of my send lane
    to = args.to or next((ep for ep, cfg in bc.ENDPOINTS.items()
                          if lane in cfg["receives_on"]), "")
    task_id = bc.make_task_id()
    frontmatter = {
        "created": bc.now_iso(),
        "schema_version": "2",
        "agent": me,
        "from": me,
        "to": to,
        "target_agent": args.target,
        "purpose": "handoff",
        "status": "open",
        "task_id": task_id,
        "kind": args.kind,
        "adapter": args.adapter,
        "repo": args.repo,
        "base_branch": args.base_branch,
        "claimed_by": "",
        "claimed_at": "",
    }
    body = (
        "## Auftrag\n"
        f"{args.text}\n\n"
        "## Akzeptanzkriterien\n"
        "- [ ] Ergebnis liegt im inbox/ mit demselben task_id\n\n"
        "## Ergebnis\n"
        "<wird vom Empfänger gefüllt>\n"
    )
    out_path = bc.lane_outbox(lane) / f"task-{task_id}.md"
    bc.write_text_utf8(out_path, bc.build_document(frontmatter, body))
    print(f"[{me}] Task → lane-{lane}/outbox/{out_path.name} (adapter={args.adapter}, to={to})")
    return 0
```

(c) In `scripts/handoff_collect.py`, make `collect_once` iterate the send-lane inboxes (where my replies land — I sent on send_lane, replies come back in that lane's inbox). Replace line 49:

```python
    lane = bc.send_lane()
    results = sorted(bc.lane_inbox(lane).glob("result-*.md"))
```

and replace `bc.processed_dir()` (line 58) with `bc.lane_processed(lane)`.

- [ ] **Step 4: Run tests + regression**

Run: `cd scripts && python test_lanes.py && python test_stage1.py && python test_hardening.py && python test_claude_adapter.py`
Expected: writer test green; `test_collect_shows_pull_hint` in test_stage1 still green (it uses the default lane via legacy helpers — verify; if it writes to `bc.inbox_dir()` that is default-lane = A-to-B, and collector with endpoint claude@laptop-a sends on A-to-B → inbox matches). All suites green.

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff_write.py scripts/handoff_collect.py scripts/test_lanes.py
git commit -m "feat(bridge): endpoint-relative writer (--adapter/--to) + collector"
```

---

## Task 7: B→A end-to-end echo roundtrip (bidirectionality proof)

**Files:**
- Test: `scripts/test_lanes.py` (extend: full B→A roundtrip with swapped endpoint config)

This proves the core user goal: the SAME scripts, reversed by configuration only.

- [ ] **Step 1: Write the failing test**

Append to `scripts/test_lanes.py` (before `main`, add to list):

```python
def test_b_to_a_roundtrip_echo() -> None:
    """B writes (codex@laptop-b sends on B-to-A), A polls (claude@laptop-a
    receives on B-to-A) and echoes, B collects. Direction reversed by config."""
    root = _fresh_bridge("codex@laptop-b")
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    # B writes the task.
    assert hw.main(["spiegel mich bitte", "--adapter", "echo"]) == 0

    # Switch identity to A and poll.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "claude@laptop-a"
    import handoff_poll as hp; importlib.reload(hp)
    import runners; importlib.reload(runners)
    n = hp.poll_once()
    assert n == 1, f"A sollte genau 1 Task in B-to-A verarbeiten, war {n}"

    # Switch back to B and collect.
    os.environ["DUAL_BRIDGE_ENDPOINT"] = "codex@laptop-b"
    importlib.reload(bc)
    import handoff_collect as hc; importlib.reload(hc)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        got = hc.collect_once(peek=True)
    assert got == 1, "B sollte genau 1 Result einsammeln"
    assert "spiegel mich bitte" in buf.getvalue()
    print("  roundtrip OK — B→A echo end-to-end, reversed by configuration only")
```

- [ ] **Step 2: Run test to verify it fails (or passes)**

Run: `cd scripts && python test_lanes.py`
Expected: PASS if Tasks 1–6 are correct. If it FAILS, the failure pinpoints which wiring (write-lane, poll-lane, collect-lane) is off — fix there, do not weaken the test.

- [ ] **Step 3: (only if red) fix the wiring**

Trace the lane the task lands in vs. the lane A polls vs. the lane B collects from. All three must be `B-to-A`. Adjust the helper used in the offending script.

- [ ] **Step 4: Run the full test matrix**

Run: `cd scripts && python test_lanes.py && python test_hardening.py && python test_stage1.py && python test_claude_adapter.py`
Expected: every suite green.

- [ ] **Step 5: Commit**

```bash
git add scripts/test_lanes.py
git commit -m "test(bridge): B→A echo roundtrip proves config-only reversibility"
```

---

## Task 8: Update wiki TODOs (the "A" deliverable)

**Files:**
- Modify: `C:\Users\domes\wiki\wiki\todos\2026-05-30-dual-bridge-haertung-vor-stage1.md`
- Modify: `C:\Users\domes\wiki\wiki\todos\2026-05-30-dual-bridge-modulare-v2.md`

Not code — documentation reconciliation. No tests; this is a config/doc change per the TDD skill's "when NOT to use TDD".

- [ ] **Step 1: Mark P0 hardening items done**

In `2026-05-30-dual-bridge-haertung-vor-stage1.md`, under "Sollte (Robustheit)", change the P0-Nachfund checkbox to `[x]` and append to the Log:

```markdown
- 2026-05-31 P0-Crash-Fenster + Sibling-Surrender-Waise + task_id-Injection
  (inkl. Recovery-Pfad) gefixt per Bugfix-TDD (Commits acc8441, 8be392e),
  Codex-Verifier-gegengeprüft. test_hardening 10/10, test_stage1 17/17.
  Status: F3/F5–F10 bleiben offen (nicht-blockierend).
```

- [ ] **Step 2: Rewrite the modulare-v2 acceptance criteria to the lean scope**

In `2026-05-30-dual-bridge-modulare-v2.md`, replace the "## Akzeptanzkriterien" block with the lean set (lanes + adapter-field + RUNNERS dict + endpoint-relative CLI + claude runner; explicitly NO FileBridgeStore/Router-Registry/Transport-Abstraktion), and add a Log line:

```markdown
- 2026-05-31 Scope abgerüstet nach Multi-Perspektiven-Review + Codex-Verifier:
  richtungsgetrennte Lanes, adapter-Feld + RUNNERS-dict, endpoint-relative CLI,
  echter claude -p Runner. OHNE Codex' 4-Schichten-Infra (YAGNI für 2 Laptops).
  Spec: dual-bridge/docs/superpowers/specs/2026-05-31-dual-bridge-stage2a-modulare-v2-design.md
  Umgesetzt in dual-bridge Commits (Stage 2a). Review-Loop = Stage 2b.
```

- [ ] **Step 3: Commit (wiki is a separate repo — surgical add)**

```bash
cd /c/Users/domes/wiki && git add wiki/wiki/todos/2026-05-30-dual-bridge-haertung-vor-stage1.md wiki/wiki/todos/2026-05-30-dual-bridge-modulare-v2.md && git commit -m "docs(dual-bridge): P0-Härtung erledigt, v2-Scope auf schlanke Variante abgerüstet"
```

(If the wiki is not a git repo or has unrelated drift, skip the commit and just save the files — per global CLAUDE.md §7, never `git add -A` in a drifted repo.)

---

## Final verification

- [ ] Run every suite once more:

```bash
cd scripts && python test_hardening.py && python test_stage1.py && python test_lanes.py && python test_claude_adapter.py
```

Expected: `test_hardening` 10/10, `test_stage1` 17/17, `test_lanes` all green (lane/runner/dispatch/to-filter/writer/roundtrip), `test_claude_adapter` 4/4.

- [ ] Confirm the core success criteria from the spec are met: B→A works by config (Task 7), Codex→Claude runner is real (Task 4), `adapter` separates model from `kind` (Task 5), two-poller race structurally impossible (Task 1 lanes), git only in codex runner (Task 2/3).
- [ ] Live proof of `run_claude` against the real `claude` CLI is a SEPARATE manual step (P007), not part of this plan's unit suites.
