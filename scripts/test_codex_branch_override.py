"""Branch-override unit tests for run_codex_task (Stage-2b foundation).
No real codex/git network — we monkeypatch the git helpers and the codex call.
conftest.py isolates DUAL_BRIDGE_ROOT."""
from __future__ import annotations

import adapter_git as ag
import codex_adapter as ca


def test_run_codex_task_uses_branch_override(monkeypatch, tmp_path):
    """When branch= is given, that exact branch name is checked out."""
    used = {}

    def fake_clone(repo, base_branch, workdir, **kwargs):
        (workdir / ".git").mkdir(parents=True, exist_ok=True)
        return workdir

    def fake_checkout(workdir, branch):
        used["checkout_branch"] = branch

    class _Proc:
        returncode = 0
        stdout = "done"
        stderr = ""

    monkeypatch.setattr(ag, "_git_clone_or_pull", fake_clone)
    monkeypatch.setattr(ag, "_git_checkout_branch", fake_checkout)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")
    # subprocess.run mock keeps _resolve_base_branch's git probes stubbed; the
    # codex call now goes through the _run_codex_exec seam (Popen + tree-kill).
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "_run_codex_exec", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ag, "_git_status_porcelain", lambda _w: [])  # no changes → no commit

    res = ca.run_codex_task(
        auftrag="x", repo="r", base_branch="main", task_id="t-1",
        workroot=tmp_path, branch="bridge/loop-abc",
    )
    assert used.get("checkout_branch") == "bridge/loop-abc"
    assert res.status == "done"


def test_run_codex_task_defaults_to_task_branch(monkeypatch, tmp_path):
    """Without branch=, the legacy bridge/task-<id> name is used (Stage-1 unchanged)."""
    used = {}
    monkeypatch.setattr(ag, "_git_clone_or_pull",
                        lambda r, b, w, **kw: (w / ".git").mkdir(parents=True, exist_ok=True) or w)
    monkeypatch.setattr(ag, "_git_checkout_branch",
                        lambda w, branch: used.__setitem__("b", branch))
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")

    class _Proc:
        returncode = 0
        stdout = "done"
        stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "_run_codex_exec", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ag, "_git_status_porcelain", lambda _w: [])

    ca.run_codex_task(auftrag="x", repo="r", base_branch="main",
                      task_id="t-99", workroot=tmp_path)
    assert used.get("b") == "bridge/task-t-99"


def test_clone_or_pull_prefers_existing_remote_branch(monkeypatch, tmp_path):
    """If origin/<prefer_branch> exists, _git_clone_or_pull resets to it, not base."""
    workdir = tmp_path / "wd"
    (workdir / ".git").mkdir(parents=True)
    calls = []

    def fake_run_git(wd, *args, **kwargs):
        calls.append(args)
        class _CP:
            returncode = 0
            stdout = ""
            stderr = ""
        # `git ls-remote --heads origin <branch>` returns a non-empty line if it exists
        if args[:2] == ("ls-remote", "--heads"):
            _CP.stdout = "abc123\trefs/heads/bridge/loop-abc\n"
        return _CP()

    monkeypatch.setattr(ag, "_run_git", fake_run_git)
    ag._git_clone_or_pull("repo", "main", workdir, prefer_branch="bridge/loop-abc")

    # It must have reset to origin/bridge/loop-abc, not origin/main.
    assert ("reset", "--hard", "origin/bridge/loop-abc") in calls
    assert ("reset", "--hard", "origin/main") not in calls


def test_clone_or_pull_falls_back_to_base_when_branch_absent(monkeypatch, tmp_path):
    """If origin/<prefer_branch> does NOT exist, fall back to base_branch."""
    workdir = tmp_path / "wd"
    (workdir / ".git").mkdir(parents=True)
    calls = []

    def fake_run_git(wd, *args, **kwargs):
        calls.append(args)
        class _CP:
            returncode = 0
            stdout = ""        # ls-remote returns empty → branch absent
            stderr = ""
        return _CP()

    monkeypatch.setattr(ag, "_run_git", fake_run_git)
    ag._git_clone_or_pull("repo", "main", workdir, prefer_branch="bridge/loop-new")
    assert ("reset", "--hard", "origin/main") in calls


def test_codex_runner_forwards_branch_from_fm(monkeypatch, tmp_path):
    """_codex_runner reads fm['branch'] and passes it to run_codex_task."""
    captured = {}

    def fake_task(**kw):
        captured.update(kw)
        from runners import RunnerResult
        return RunnerResult(status="done", antwort="ok")

    monkeypatch.setattr(ca, "run_codex_task", fake_task)
    fm = {"task_id": "t-7", "repo": "r", "base_branch": "main",
          "branch": "bridge/loop-zzz"}
    res = ca._codex_runner(auftrag="build it", fm=fm, workroot=tmp_path)
    assert res.status == "done"
    assert captured.get("branch") == "bridge/loop-zzz"


def test_codex_runner_branch_absent_is_none(monkeypatch, tmp_path):
    """No fm['branch'] → branch=None (legacy task-branch behaviour)."""
    captured = {}

    def fake_task(**kw):
        captured.update(kw)
        from runners import RunnerResult
        return RunnerResult(status="done", antwort="ok")

    monkeypatch.setattr(ca, "run_codex_task", fake_task)
    res = ca._codex_runner(auftrag="x", fm={"task_id": "t-8"}, workroot=tmp_path)
    assert captured.get("branch") is None


def test_run_codex_task_captures_diff(monkeypatch, tmp_path):
    """run_codex_task returns the build diff (git diff base..HEAD) on success."""
    monkeypatch.setattr(ag, "_git_clone_or_pull",
                        lambda r, b, w, **k: (w / ".git").mkdir(parents=True, exist_ok=True) or w)
    monkeypatch.setattr(ag, "_git_checkout_branch", lambda w, branch: None)
    monkeypatch.setattr(ca.shutil, "which", lambda _n: "C:/fake/codex.exe")

    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "_run_codex_exec", lambda *a, **k: _Proc())
    monkeypatch.setattr(ca, "parse_codex_output", lambda _s: "answer")
    monkeypatch.setattr(ag, "_git_status_porcelain", lambda _w: ["scripts/runners.py"])
    monkeypatch.setattr(ag, "_git_commit_and_push", lambda w, b, m: "abc123")
    monkeypatch.setattr(ag, "_git_diff", lambda w, base: "--- a\n+++ b\n+new line\n")

    res = ca.run_codex_task(auftrag="x", repo="r", base_branch="main",
                            task_id="t-d", workroot=tmp_path, branch="bridge/loop-d")
    assert res.status == "done"
    assert res.diff == "--- a\n+++ b\n+new line\n"


# --- Auth-Pfad + klarere Clone-Fehler-Diagnose (Fix 2026-06-06: privates Repo
#     anonym gesehen -> irrefuehrendes 'branch not found' -> rc=3) ----------------

def _fake_fill(stdout, returncode=0):
    """Stub fuer `git credential fill` (erstes subprocess.run im resolver)."""
    class _Fill:
        pass
    _Fill.returncode = returncode
    _Fill.stdout = stdout
    _Fill.stderr = ""
    return lambda *a, **k: _Fill()


def test_resolve_https_credential_token_in_file_not_argv_or_env(monkeypatch):
    """HTTPS-Remote -> GIT_ASKPASS + store-Datei. Das Token liegt in der DATEI,
    NICHT in env-Values (kein Env-Leak) und NICHT auf einer git-Kommandozeile."""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill(
        "protocol=https\nhost=github.com\nusername=bob\npassword=ghp_secrettoken\n"))
    cred = ag._resolve_https_credential("https://github.com/owner/private-repo")
    try:
        # env traegt nur Pfade/Flags, KEIN Token:
        assert set(cred.env) == {"GIT_ASKPASS", "GIT_BRIDGE_CREDFILE",
                                 "GIT_TERMINAL_PROMPT"}
        assert not any("ghp_secrettoken" in str(v) for v in cred.env.values())
        assert cred.env["GIT_TERMINAL_PROMPT"] == "0"
        # Token liegt in der store-Datei im git-store-Format:
        assert cred.store_path is not None and cred.store_path.exists()
        assert cred.env["GIT_BRIDGE_CREDFILE"] == cred.store_path.as_posix()
        content = cred.store_path.read_text(encoding="utf-8")
        assert content == "https://bob:ghp_secrettoken@github.com\n"
        # Der askpass-Wrapper existiert und ruft den Helper (kein Token darin):
        assert cred.wrapper_path is not None and cred.wrapper_path.exists()
        wrap = cred.wrapper_path.read_text(encoding="utf-8")
        assert "git_askpass_helper.py" in wrap
        assert "ghp_secrettoken" not in wrap
        # Haertung: ein-Arg-quoting statt %*/$@ (kein cmd-Metazeichen-Restkanal).
        import os as _os
        if _os.name == "nt":
            assert "%~1" in wrap and "%*" not in wrap
            assert "setlocal" in wrap
        else:
            assert '"$1"' in wrap
    finally:
        cred.cleanup()


def test_askpass_helper_username_vs_password_heuristic(tmp_path):
    """Username-Prompt -> user, Password-Prompt -> token; ein Prompt der BEIDE
    Woerter nennt faellt auf password (default) zurueck."""
    import subprocess
    import sys
    store = tmp_path / "c.store"
    store.write_text("https://usr:tok@h\n", encoding="utf-8")
    env = ca.safe_subprocess_env({"GIT_BRIDGE_CREDFILE": store.as_posix()})

    def ask(prompt):
        return subprocess.run([sys.executable, str(ca._ASKPASS_HELPER), prompt],
                              capture_output=True, text=True, env=env).stdout.strip()

    assert ask("Username for 'https://h': ") == "usr"
    assert ask("Password for 'https://usr@h': ") == "tok"
    # beide Woerter -> password gewinnt (sonst wuerde der User als Passwort gelten)
    assert ask("Password for username x: ") == "tok"


def test_askpass_helper_missing_file_is_empty(tmp_path):
    """Fehlende/leere store-Datei -> leere Antwort (git promptet, kein Crash)."""
    import subprocess
    import sys
    env = ca.safe_subprocess_env(
        {"GIT_BRIDGE_CREDFILE": str(tmp_path / "does-not-exist.store")})
    r = subprocess.run([sys.executable, str(ca._ASKPASS_HELPER), "Username: "],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_resolve_https_credential_cleans_store_if_wrapper_fails(monkeypatch):
    """Wirft _write_askpass_wrapper, darf die token-tragende store-Datei NICHT
    leaken -> leeres _Cred, Datei geloescht."""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill(
        "protocol=https\nhost=github.com\nusername=bob\npassword=tok\n"))
    captured = {}

    def boom():
        # Pfad der store-Datei wird VOR dem Wurf vom Resolver erzeugt; wir koennen
        # ihn ueber den TEMP-Glob nach dem Aufruf pruefen.
        raise OSError("disk full")
    monkeypatch.setattr(ag, "_write_askpass_wrapper", boom)

    import glob
    import tempfile
    before = set(glob.glob(tempfile.gettempdir() + "/bridge-cred-*.store"))
    cred = ag._resolve_https_credential("https://github.com/o/r")
    after = set(glob.glob(tempfile.gettempdir() + "/bridge-cred-*.store"))
    assert cred.env == {} and cred.store_path is None
    assert after == before    # keine neue store-Datei uebrig


def test_resolve_https_credential_urlencodes_special_chars(monkeypatch):
    """SECURITY-Regression: Sonderzeichen in user/pw (', :, @, $, Leerzeichen)
    werden URL-encoded -> KEINE Shell-Injection, KEINE zweite store-Zeile, kein
    Zerbrechen des Eintrags. (Der fruehere inline-`!sh`-Helper war hier verwundbar.)"""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill(
        "protocol=https\nhost=h.example\nusername=a'b\npassword=p:w@d$(x) y\n"))
    cred = ag._resolve_https_credential("https://h.example/o/r")
    try:
        content = cred.store_path.read_text(encoding="utf-8")
        # genau EINE Zeile, alle Sonderzeichen prozent-codiert, kein rohes $( ) ' @ :
        assert content.count("\n") == 1
        body = content.split("://", 1)[1].rsplit("@", 1)[0]   # user:pw-Teil
        assert "'" not in body and "$(" not in body and " " not in body
        assert "%27" in body            # ' -> %27
        assert "%24" in body            # $ -> %24
        assert content.endswith("@h.example\n")
    finally:
        cred.cleanup()


def test_askpass_helper_roundtrips_special_chars(tmp_path):
    """Der askpass-Helper dekodiert user/token aus der store-Datei korrekt zurueck
    und unterscheidet Username- vs Password-Prompt -- ohne Shell (kein Inject).

    NB: KEIN monkeypatch auf subprocess.run -- wir rufen den echten Helper als
    echten Subprozess auf (ein Patch wuerde den Helper-Lauf selbst kapern)."""
    import subprocess
    import sys
    import urllib.parse
    # store-Datei direkt im git-store-Format anlegen (wie der Resolver es taete).
    user = "a'b"
    token = "p:w@d$(touch %s) y" % (tmp_path / "PWNED")
    enc = lambda s: urllib.parse.quote(s, safe="")
    store = tmp_path / "cred.store"
    store.write_text(f"https://{enc(user)}:{enc(token)}@h.example\n", encoding="utf-8")

    env = ca.safe_subprocess_env({"GIT_BRIDGE_CREDFILE": store.as_posix()})
    u = subprocess.run([sys.executable, str(ca._ASKPASS_HELPER),
                        "Username for 'https://h.example': "],
                       capture_output=True, text=True, env=env)
    p = subprocess.run([sys.executable, str(ca._ASKPASS_HELPER),
                        "Password for x: "],
                       capture_output=True, text=True, env=env)
    assert u.stdout.strip() == user
    assert p.stdout.strip() == token
    # die Shell-Payload im Token wurde NICHT ausgefuehrt:
    assert not (tmp_path / "PWNED").exists()


def test_resolve_https_credential_skips_local_and_ssh():
    """Lokale/SSH-Remotes brauchen keinen Helper -> leeres _Cred, keine Datei."""
    for r in ("C:/tmp/origin.git", "git@github.com:o/r.git", "/home/x/origin"):
        cred = ag._resolve_https_credential(r)
        assert cred.env == {}
        assert cred.store_path is None and cred.wrapper_path is None


def test_resolve_https_credential_empty_when_fill_fails(monkeypatch):
    """`git credential fill` rc!=0 -> leeres _Cred (git nutzt seine eigene Kette)."""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill("", returncode=1))
    cred = ag._resolve_https_credential("https://github.com/o/r")
    assert cred.env == {} and cred.store_path is None


def test_resolve_https_credential_empty_when_no_host(monkeypatch):
    """Ohne host (oder user/pw) -> leeres _Cred, keine halbe store-Zeile."""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill(
        "username=bob\npassword=tok\n"))   # kein host
    cred = ag._resolve_https_credential("https://github.com/o/r")
    assert cred.env == {} and cred.store_path is None


def test_clone_or_pull_deletes_store_and_wrapper(monkeypatch, tmp_path):
    """Store-Datei UND askpass-Wrapper werden nach den git-Calls geloescht --
    auch wenn der Clone fehlschlaegt (finally)."""
    monkeypatch.setattr(ag.subprocess, "run", _fake_fill(
        "protocol=https\nhost=github.com\nusername=bob\npassword=tok\n"))
    seen = {}

    def fake_run_git(wd, *args, cred=None):
        # store-Datei + Wrapper existieren WAEHREND der git-Calls
        if cred is not None and cred.store_path is not None:
            seen["store_during"] = cred.store_path.exists()
            seen["wrap_during"] = cred.wrapper_path.exists()
            seen["store"] = cred.store_path
            seen["wrap"] = cred.wrapper_path
        class _CP:
            returncode = 1            # Clone schlaegt fehl
            stdout = ""
            stderr = "boom"
        return _CP()
    monkeypatch.setattr(ag, "_run_git", fake_run_git)

    workdir = tmp_path / "wd"   # kein .git -> Fresh-Clone-Pfad
    try:
        ag._git_clone_or_pull("https://github.com/o/r", "main", workdir)
    except RuntimeError:
        pass
    assert seen.get("store_during") is True and seen.get("wrap_during") is True
    assert not seen["store"].exists() and not seen["wrap"].exists()  # aufgeraeumt


def test_diagnose_clone_failure_flags_auth_when_branch_visible(monkeypatch):
    """'branch not found' + remote-sichtbarer Branch -> AUTH-Diagnose statt
    Parroting des irrefuehrenden git-Texts."""
    def fake_run_git(wd, *args, cred=None):
        class _CP:
            returncode = 0
            stdout = "abc\trefs/heads/main\n"   # Branch IST remote sichtbar
            stderr = ""
        return _CP()
    monkeypatch.setattr(ag, "_run_git", fake_run_git)

    msg = ag._diagnose_clone_failure(
        "https://github.com/o/r", "main",
        "fatal: Remote branch main not found in upstream origin",
        cred=ag._Cred(env={}))
    assert "AUTH" in msg
    assert "Auth/Token" in msg


def test_diagnose_clone_failure_passthrough_for_real_branch_miss(monkeypatch):
    """Branch wirklich nicht sichtbar -> kein AUTH, git-Wortlaut bleibt erhalten.

    'Wirklich fehlend' ist nur beweisbar, wenn eine Credential AUFGELOEST war
    (cred.env nicht leer) und der Re-Probe TROTZDEM leer blieb. Bei leerem
    cred.env lief der Re-Probe selbst anonym -> Leere beweist nichts und wird
    jetzt als AUTH gewertet (siehe Folge-Test). Korrigiert die 2026-06-06-
    Fehldiagnose."""
    def fake_run_git(wd, *args, cred=None):
        class _CP:
            returncode = 0
            stdout = ""              # ls-remote leer -> Branch fehlt echt
            stderr = ""
        return _CP()
    monkeypatch.setattr(ag, "_run_git", fake_run_git)

    raw = "fatal: Remote branch nope not found in upstream origin"
    msg = ag._diagnose_clone_failure("https://github.com/o/r", "nope", raw,
                                     cred=ag._Cred(env={"GIT_ASKPASS": "x"}))
    assert "AUTH" not in msg
    assert raw in msg


def test_diagnose_clone_failure_empty_reprobe_without_cred_is_auth(monkeypatch):
    """Leerer Re-Probe OHNE aufgeloeste Credential -> AUTH, nicht 'Branch fehlt'.
    Das war die eigentliche 2026-06-06-Ursache (privates Repo, anonymer Clone)."""
    def fake_run_git(wd, *args, cred=None):
        class _CP:
            returncode = 0
            stdout = ""              # anonymer Re-Probe sieht 0 Refs
            stderr = ""
        return _CP()
    monkeypatch.setattr(ag, "_run_git", fake_run_git)

    raw = "fatal: Remote branch main not found in upstream origin"
    msg = ag._diagnose_clone_failure("https://github.com/o/r", "main", raw,
                                     cred=ag._Cred(env={}))
    assert "AUTH" in msg
    assert raw in msg


def test_diagnose_clone_failure_passthrough_for_other_errors():
    """Andere Clone-Fehler (kein 'not found in upstream') unveraendert."""
    raw = "fatal: could not create work tree dir: Permission denied"
    msg = ag._diagnose_clone_failure("https://github.com/o/r", "main", raw,
                                     cred=ag._Cred(env={}))
    assert msg == f"git clone failed: {raw}"
