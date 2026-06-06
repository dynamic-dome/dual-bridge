"""Regression tests for the F1/F2/F4 hardening fixes.

Runs against an isolated temp bridge root (DUAL_BRIDGE_ROOT) — never touches
the real Sharepoint. Pure stdlib + assert, no pytest needed:
    python test_hardening.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _fresh_bridge() -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-test-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    return root


def test_f2_unique_ids() -> None:
    """F2: many ids created in a tight loop must all be unique."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    ids = [bc.make_task_id() for _ in range(5000)]
    assert len(set(ids)) == len(ids), f"ID-Kollision: {len(ids) - len(set(ids))} Duplikate"
    print(f"  F2 OK — 5000 IDs, 0 Kollisionen (Beispiel: {ids[0]})")


def test_f2_exclusive_write() -> None:
    """F2/F1: exclusive write refuses to overwrite an existing file."""
    import bridge_common as bc
    _fresh_bridge()
    bc.ensure_dirs()
    p = bc.outbox_dir() / "excl-test.md"
    assert bc.write_text_exclusive(p, "first") is True
    assert bc.write_text_exclusive(p, "second") is False, "Overwrite hätte verhindert werden müssen"
    assert p.read_text(encoding="utf-8") == "first", "Inhalt wurde überschrieben!"
    print("  F2 OK — write_text_exclusive verhindert stilles Überschreiben")


def test_f3_atomic_write() -> None:
    """F3: atomic write leaves no temp file behind and writes full content."""
    import bridge_common as bc
    _fresh_bridge()
    bc.ensure_dirs()
    p = bc.outbox_dir() / "atomic-test.md"
    bc.write_text_atomic(p, "voller Inhalt mit Ümlaut")
    assert p.read_text(encoding="utf-8-sig") == "voller Inhalt mit Ümlaut"
    leftover = list(bc.outbox_dir().glob(".tmp-*"))
    assert not leftover, f"Temp-Datei nicht aufgeräumt: {leftover}"
    print("  F3 OK — atomic write, kein Temp-Rest, Umlaut erhalten")


def test_f4_stranded_claim_gets_archived() -> None:
    """F4: a .claimed-* task left in outbox (move had failed) is re-archived
    on the next poll_once, and is NOT re-processed."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    _fresh_bridge()
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    # Simulate a stranded done-but-not-moved claimed task.
    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "done", "task_id": task_id,
        "kind": "echo", "claimed_by": "laptop-b-worker@TESTDEV", "claimed_at": bc.now_iso(),
    }
    stranded = bc.outbox_dir() / f"task-{task_id}.claimed-TESTDEV-abcd1234.md"
    bc.write_text_utf8(stranded, bc.build_document(fm, "## Auftrag\nx\n"))
    # Its result already exists (it was written before the move failed).
    bc.write_text_utf8(bc.inbox_dir() / f"result-{task_id}.md", "done earlier")

    n = hp._poll_lane(bc.DEFAULT_LANE)
    assert n == 0, "Stranded-Task darf NICHT als neu verarbeitet zählen"
    assert not stranded.exists(), "Stranded-Task wurde nicht aus outbox archiviert"
    assert (bc.processed_dir() / stranded.name).exists(), "Stranded-Task nicht in _processed"
    print("  F4 OK — liegengebliebener .claimed-Task nachgeholt archiviert, nicht reprozessiert")


def test_p0_open_claim_without_result_is_not_lost() -> None:
    """P0: a .claimed-* task that crashed AFTER claim but BEFORE its result was
    written (status:open, no inbox/result-*.md) must NOT be silently archived
    into _processed/. It has to be requeued (back to task-<id>.md, status:open)
    so the next pass re-processes it. The old code archived it blindly -> loss."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "echo", "claimed_by": "laptop-b-worker@TESTDEV",
        "claimed_at": bc.now_iso(),
    }
    # A stranded claim with status:open and NO result -> the crash-before-result case.
    stranded = bc.outbox_dir() / f"task-{task_id}.claimed-TESTDEV-deadbeef.md"
    bc.write_text_utf8(stranded, bc.build_document(fm, "## Auftrag\nbearbeite mich\n"))

    hp._poll_lane(bc.DEFAULT_LANE)

    # The crashed claim's exact filename must NOT end up in _processed/ — that
    # would be the silent loss (archived without ever being answered).
    assert not (bc.processed_dir() / stranded.name).exists(), \
        "P0: open claim ohne Result wurde fälschlich nach _processed/ archiviert (Taskverlust!)"

    # The task must survive in one of the legitimate forms: either requeued as an
    # open task waiting for the next pass, OR already re-processed within the same
    # pass (a result now exists). What must never happen: gone with no trace.
    requeued = bc.outbox_dir() / f"task-{task_id}.md"
    result = bc.inbox_dir() / f"result-{task_id}.md"
    leftover_claim = list(bc.outbox_dir().glob(f"task-{task_id}.claimed-*.md"))
    assert requeued.exists() or result.exists() or leftover_claim, \
        "P0: open claim ohne Result ist spurlos verschwunden"
    if requeued.exists() and not result.exists():
        rfm, _ = bc.parse_frontmatter(bc.read_text_utf8(requeued))
        assert rfm.get("status") == "open", \
            f"requeued task muss status:open haben, war {rfm.get('status')!r}"
    print("  P0 OK — open claim ohne Result überlebt (requeued bzw. nachverarbeitet, nicht verloren)")


def test_task_id_validation_rejects_injection() -> None:
    """task_id flows unchecked into result filenames (handoff_poll.py:108) and
    git branch names (codex_adapter.py:166). A task_id with '../' or git/branch
    metacharacters is a path-traversal / branch-injection vector — the trust
    boundary is the shared Drive folder, not the laptop. is_valid_task_id must
    accept legitimate make_task_id() output and reject anything else."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)

    # Real ids must pass.
    for _ in range(20):
        tid = bc.make_task_id()
        assert bc.is_valid_task_id(tid), f"echte task_id fälschlich abgelehnt: {tid!r}"

    # Injection / traversal attempts must be rejected.
    bad = [
        "../../etc/passwd",
        "..\\..\\windows",
        "a/b",
        "a b",                 # space -> separate git arg
        "--force",             # git flag injection
        "x;rm -rf /",
        "T1$(whoami)",
        "T1\nmalice",
        "",
        "x" * 200,             # absurdly long
        "task.claimed-evil",   # would collide with the claim marker
    ]
    for tid in bad:
        assert not bc.is_valid_task_id(tid), f"bösartige task_id fälschlich akzeptiert: {tid!r}"
    print("  task_id OK — echte IDs akzeptiert, Injection/Traversal abgelehnt")


def test_poll_skips_task_with_bad_id() -> None:
    """A task whose frontmatter carries an invalid task_id must not be processed
    (no result file written under a traversal path, no codex/branch call)."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    # Filename is safe; the DANGEROUS id lives in the frontmatter.
    safe_name_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": "../evil",
        "kind": "echo", "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{safe_name_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))

    produced = hp.process_one(task, lane=bc.DEFAULT_LANE)
    assert produced is False, "Task mit ungültiger task_id darf nicht verarbeitet werden"
    # No result anywhere outside the inbox (traversal) and none for the evil id.
    assert not (bc.inbox_dir() / "result-../evil.md").exists()
    assert not list(bc.bridge_root().glob("**/evil*")), "Traversal-Artefakt entstanden"
    print("  poll OK — Task mit Injection-task_id übersprungen, kein Traversal-Artefakt")


def test_recovery_validates_task_id() -> None:
    """task_id-Injection via the stranded-claim recovery path (Codex verifier
    finding). poll_once reads task_id from a .claimed-*'s frontmatter and uses it
    for inbox/result-<id>.md and _requeue_claimed — the process_one guard does NOT
    cover this path. A corrupt/hostile .claimed-* with a traversal task_id must be
    quarantined, not honoured."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    # Filename is safe; the DANGEROUS id lives in the stranded claim's frontmatter.
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": "../../evil",
        "kind": "echo", "claimed_by": "laptop-b-worker@X", "claimed_at": bc.now_iso(),
    }
    safe_name_id = bc.make_task_id()
    stranded = bc.outbox_dir() / f"task-{safe_name_id}.claimed-X-12345678.md"
    bc.write_text_utf8(stranded, bc.build_document(fm, "## Auftrag\nx\n"))

    hp._poll_lane(bc.DEFAULT_LANE)

    # No traversal artifact anywhere under the bridge root, and no requeued/result
    # file built from the evil id.
    assert not list(bc.bridge_root().glob("**/evil*")), "Traversal-Artefakt über Recovery-Pfad entstanden"
    assert not (bc.outbox_dir() / "task-../../evil.md").exists()
    print("  recovery OK — stranded claim mit Injection-task_id quarantäniert, kein Traversal")


def test_sibling_surrender_leaves_no_orphan() -> None:
    """Sibling-Surrender bug (bridge_common.py:222-230): when claim_task loses the
    race (a sibling .claimed-* for the same task_id already exists), it must NOT
    leave its own .claimed-* file orphaned in the outbox. The loser cleans up its
    own claim; the winner's claim stands. The old code did `pass` -> orphan left."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    bc.ensure_dirs()

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "echo", "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nx\n"))

    # Simulate the winner: a pre-existing sibling claim by another device.
    winner = bc.outbox_dir() / f"task-{task_id}.claimed-OTHERDEV-11112222.md"
    bc.write_text_utf8(winner, bc.build_document(fm, "## Auftrag\nx\n"))

    # We try to claim and lose the sibling check.
    result = bc.claim_task(task, "TESTDEV")
    assert result is None, "claim_task muss bei vorhandenem Sibling None liefern"

    # Our own claim must not be left orphaned in the outbox.
    our_orphans = [
        p for p in bc.outbox_dir().glob(f"task-{task_id}.claimed-TESTDEV-*.md")
    ]
    assert not our_orphans, f"Sibling-Surrender hinterließ Waise(n): {[p.name for p in our_orphans]}"
    # The winner's claim is untouched.
    assert winner.exists(), "Winner-Claim darf nicht angetastet werden"
    print("  Sibling OK — Verlierer räumt eigene Waise weg, Winner-Claim bleibt")


def test_f1_double_claim_one_result() -> None:
    """F1: if a result already exists, process_one bails (exclusive) and the
    task is archived rather than producing a duplicate result."""
    import importlib
    import bridge_common as bc
    importlib.reload(bc)
    import handoff_poll as hp
    importlib.reload(hp)
    bc.ensure_dirs()

    task_id = bc.make_task_id()
    fm = {
        "created": bc.now_iso(), "agent": "laptop-a", "target_agent": "laptop-b",
        "purpose": "handoff", "status": "open", "task_id": task_id,
        "kind": "echo", "claimed_by": "", "claimed_at": "",
    }
    task = bc.outbox_dir() / f"task-{task_id}.md"
    bc.write_text_utf8(task, bc.build_document(fm, "## Auftrag\nhallo\n"))
    # Pretend another worker already produced the result.
    pre_existing = bc.inbox_dir() / f"result-{task_id}.md"
    bc.write_text_utf8(pre_existing, "result vom anderen worker")

    produced = hp.process_one(task, lane=bc.DEFAULT_LANE)
    assert produced is False, "process_one hätte bei existierendem Result bailen müssen"
    assert pre_existing.read_text(encoding="utf-8-sig") == "result vom anderen worker", \
        "Bestehendes Result wurde überschrieben!"
    # task should be archived, not stuck in outbox
    assert not list(bc.outbox_dir().glob(f"task-{task_id}*")), "Task blieb in outbox stecken"
    print("  F1 OK — Doppel-Claim: kein Result-Overwrite, Task archiviert statt stuck")


# --- QW3: env allowlist + QW2: UTF-8 runtime / OEM decode --------------------
import contextlib


@contextlib.contextmanager
def _env(**overrides):
    """Snapshot+restore the named env vars around a block (conftest only
    snapshots DUAL_BRIDGE_*, so we restore arbitrary vars ourselves)."""
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def test_safe_env_drops_api_keys() -> None:
    """QW3: secret keys present in os.environ must never reach a child env.
    Allowlist-only build leaks none of ANTHROPIC/OPENAI/GITHUB credentials."""
    import bridge_common as bc
    keys = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN",
            "ANTHROPIC_AUTH_TOKEN")
    with _env(**{k: "leak-me-please" for k in keys}):
        env = bc.safe_subprocess_env()
    for var in keys:
        assert var not in env, f"{var} leaked into subprocess env"
    print("  QW3 OK — API-/Token-Keys nicht im Child-Env")


def test_safe_env_drops_secret_despite_allowed_prefix() -> None:
    """Codex-Verifier Q1: a secret that matches a broad allow-prefix (e.g.
    GIT_TOKEN via GIT_, or a *_SECRET) must still be dropped by the secret
    denylist. The broad prefix must not become a credential bypass."""
    import bridge_common as bc
    leaky = ("GIT_TOKEN", "GIT_ASKPASS_SECRET", "PYTHON_API_KEY",
             "PATH_CREDENTIAL", "GIT_HUB_PASSWORD",
             # Q1 round 3: GIT_HTTP_EXTRAHEADER can carry an Authorization header.
             "GIT_HTTP_EXTRAHEADER")
    with _env(**{k: "leak-me" for k in leaky}):
        env = bc.safe_subprocess_env()
    for var in leaky:
        assert var not in env, f"{var} leaked despite secret denylist"
    print("  Q1 OK — Secrets mit erlaubtem Prefix werden trotzdem gedroppt")


def test_safe_env_drops_oauth_bearer_pat_variants() -> None:
    """Codex-Verifier Q1 round 2: bare KEY / OAuth / bearer / PAT naming that
    matches GIT_/PYTHON_ prefixes but lacks the obvious TOKEN/SECRET substring."""
    import bridge_common as bc
    leaky = ("GIT_BEARER", "GIT_OAUTH", "PYTHON_KEY", "GIT_DEPLOY_PAT",
             "GIT_AUTHORIZATION")
    with _env(**{k: "leak-me" for k in leaky}):
        env = bc.safe_subprocess_env()
    for var in leaky:
        assert var not in env, f"{var} leaked (Q1 round 2)"
    print("  Q1.2 OK — OAuth/bearer/PAT/bare-KEY Varianten gedroppt")


def test_safe_env_dual_bridge_config_reaches_child_but_secrets_dont() -> None:
    """Codex-Verifier L3 2026-06-07: the DUAL_BRIDGE_ allow-prefix lets the
    bridge's own config (DUAL_BRIDGE_CONFIG path-override, timing vars) reach a
    child process — BUT the secret denylist must still strip a secret-smelling
    DUAL_BRIDGE_* (the Telegram token). Proves the new prefix is not a bypass."""
    import bridge_common as bc
    passthrough = ("DUAL_BRIDGE_CONFIG", "DUAL_BRIDGE_CODEX_TIMEOUT",
                   "DUAL_BRIDGE_ROUND_TIMEOUT", "DUAL_BRIDGE_ENDPOINT")
    secret = ("DUAL_BRIDGE_TG_TOKEN",)
    with _env(**{k: "v" for k in (*passthrough, *secret)}):
        env = bc.safe_subprocess_env()
    for var in passthrough:
        assert var in env, f"{var} must reach the child (config inheritance)"
    for var in secret:
        assert var not in env, f"{var} leaked despite the secret denylist"
    print("  L3 OK — DUAL_BRIDGE_ Config erbt, DUAL_BRIDGE_TG_TOKEN gedroppt")


def test_safe_env_ssh_auth_sock_survives_secret_denylist() -> None:
    """Regression for the denylist: SSH_AUTH_SOCK contains 'AUTH' but is a
    legitimate transport var and must NOT be killed by the secret filter."""
    import bridge_common as bc
    with _env(SSH_AUTH_SOCK="/tmp/agent.sock"):
        env = bc.safe_subprocess_env()
    assert env.get("SSH_AUTH_SOCK") == "/tmp/agent.sock", \
        "SSH_AUTH_SOCK faelschlich vom Secret-Filter entfernt"
    print("  Q1/Q4 OK — SSH_AUTH_SOCK ueberlebt trotz 'AUTH' im Namen")


def test_safe_env_keeps_git_transport_vars() -> None:
    """Codex-Verifier Q4: SSH-agent / proxy / cert vars must survive so git
    over SSH-agent or HTTPS-proxy/corporate-cert does not silently break."""
    import bridge_common as bc
    transport = {"SSH_AUTH_SOCK": "/tmp/ssh-agent.sock",
                 "HTTPS_PROXY": "http://proxy.corp:8080",
                 "SSL_CERT_FILE": r"C:\certs\corp.pem"}
    with _env(**transport):
        env = bc.safe_subprocess_env()
    for var, val in transport.items():
        assert env.get(var) == val, f"{var} dropped — git transport would break"
    print("  Q4 OK — SSH/Proxy/Cert-Transport-Vars bleiben erhalten")


def test_safe_env_keeps_appdata_localappdata() -> None:
    """QW3 (auth-path protection): APPDATA + LOCALAPPDATA must survive the
    allowlist — without them claude/codex/node run UNAUTHENTICATED."""
    import bridge_common as bc
    with _env(APPDATA=r"C:\Users\test\AppData\Roaming",
              LOCALAPPDATA=r"C:\Users\test\AppData\Local"):
        env = bc.safe_subprocess_env()
    assert env.get("APPDATA") == r"C:\Users\test\AppData\Roaming"
    assert env.get("LOCALAPPDATA") == r"C:\Users\test\AppData\Local"
    print("  QW3 OK — APPDATA/LOCALAPPDATA bleiben erhalten (Auth-Pfad)")


def test_safe_env_keeps_path() -> None:
    """QW3: PATH must be present and non-empty, else the child cannot find its
    exe (or sub-sub tools like git inside codex)."""
    import bridge_common as bc
    with _env(PATH=os.environ.get("PATH") or r"C:\Windows\System32"):
        env = bc.safe_subprocess_env()
    # PATH may carry casing variants on Windows; accept any case-insensitive hit.
    path_val = next((v for k, v in env.items() if k.upper() == "PATH"), "")
    assert path_val, "PATH fehlt oder ist leer im Child-Env"
    print("  QW3 OK — PATH vorhanden und nicht leer")


def test_safe_env_sets_pythonutf8() -> None:
    """QW2 coupling: the child env pins PYTHONUTF8=1."""
    import bridge_common as bc
    env = bc.safe_subprocess_env()
    assert env.get("PYTHONUTF8") == "1", "PYTHONUTF8 nicht auf '1' gesetzt"
    print("  QW2 OK — PYTHONUTF8=1 im Child-Env")


def test_safe_env_extra_overlay() -> None:
    """QW3: an extra dict is overlaid last (override wins)."""
    import bridge_common as bc
    env = bc.safe_subprocess_env({"FOO": "bar", "PYTHONUTF8": "0"})
    assert env.get("FOO") == "bar", "extra-Key fehlt im Ergebnis"
    assert env.get("PYTHONUTF8") == "0", "extra-Overlay überschreibt PYTHONUTF8 nicht"
    print("  QW3 OK — extra-Dict wird zuletzt drübergelegt (override)")


def test_ensure_utf8_runtime_idempotent() -> None:
    """QW2: ensure_utf8_runtime is safe to call repeatedly; never raises."""
    import bridge_common as bc
    bc.ensure_utf8_runtime()
    bc.ensure_utf8_runtime()
    print("  QW2 OK — ensure_utf8_runtime idempotent, wirft nicht")


def test_subprocess_run_quiet_uses_oem_encoding() -> None:
    """QW2 (User-Ergänzung): the CMD-internal tool reader (tasklist) decodes the
    OEM code page via encoding='oem', not utf-8+errors='replace'."""
    import inspect
    import bridge_common as bc
    src = inspect.getsource(bc._subprocess_run_quiet)
    # Inspect only the code, not the docstring (which legitimately *mentions*
    # the old errors='replace' approach to explain the change).
    code = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
    assert 'encoding="oem"' in code or "encoding='oem'" in code, \
        "_subprocess_run_quiet nutzt kein encoding='oem'"
    assert "errors=" not in code, \
        "errors='replace' sollte durch encoding='oem' ersetzt sein"
    print("  QW2 OK — tasklist-Lesestelle nutzt encoding='oem'")


def main() -> int:
    _fresh_bridge()
    print("=== Härtungs-Regressionstests (F1/F2/F3/F4 + QW2/QW3) ===")
    tests = [
        test_f2_unique_ids,
        test_f2_exclusive_write,
        test_f3_atomic_write,
        test_f4_stranded_claim_gets_archived,
        test_p0_open_claim_without_result_is_not_lost,
        test_sibling_surrender_leaves_no_orphan,
        test_task_id_validation_rejects_injection,
        test_poll_skips_task_with_bad_id,
        test_recovery_validates_task_id,
        test_f1_double_claim_one_result,
        test_safe_env_drops_api_keys,
        test_safe_env_drops_secret_despite_allowed_prefix,
        test_safe_env_drops_oauth_bearer_pat_variants,
        test_safe_env_ssh_auth_sock_survives_secret_denylist,
        test_safe_env_keeps_git_transport_vars,
        test_safe_env_keeps_appdata_localappdata,
        test_safe_env_keeps_path,
        test_safe_env_sets_pythonutf8,
        test_safe_env_extra_overlay,
        test_ensure_utf8_runtime_idempotent,
        test_subprocess_run_quiet_uses_oem_encoding,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            print(f"  FAIL {t.__name__}: {exc}")
            failed += 1
    print("=" * 48)
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
