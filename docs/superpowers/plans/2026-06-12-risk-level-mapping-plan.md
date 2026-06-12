# Risk-Level-Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforced Policy-Tabelle kind/adapter → read/build/ops mit Ops-Verb-Scan, fail-closed an Sender (handoff_write), Empfänger (handoff_poll) und DCO-Pfad (job_poll); plus Etikett-Vorarbeit in loop_driver.

**Architecture:** Neues eigenständiges Modul `scripts/risk_policy.py` (Vorbild `secret_gate.py`: kein Bridge-I/O, pure Funktionen) mit einer Funktion `check_task()`, die alle drei Enforcement-Punkte aufrufen. Spec: `docs/superpowers/specs/2026-06-12-risk-level-mapping-design.md`.

**Tech Stack:** Python stdlib (re, dataclasses), pytest. Suite läuft mit `cd scripts && python -X utf8 -m pytest -q` (aktuell 380 grün; Tests sind plain functions + assert, isoliert via `DUAL_BRIDGE_ROOT`-Env auf tmp dir — NIE gegen den echten Sharepoint, Regel §3).

**Wichtig (Reihenfolge):** Task 2 (loop_driver-Etikett) MUSS vor Task 4 (handoff_poll-Enforcement) liegen — sonst lehnt der Empfänger produktive Ping-Pong-Runden-Tasks ab (`kind: echo` + `adapter: codex` ist heute hartkodiert).

---

### Task 1: Modul `risk_policy.py` (Policy-Tabelle + check_task)

**Files:**
- Create: `scripts/risk_policy.py`
- Create: `scripts/test_risk_policy.py`

- [ ] **Step 1: Failing Tests schreiben**

`scripts/test_risk_policy.py` anlegen (Stil wie `test_lanes.py`: plain functions, assert, pytest-kompatibel):

```python
"""Risk-Level-Mapping tests (spec 2026-06-12-risk-level-mapping-design.md).
Pure stdlib + assert: python -X utf8 -m pytest test_risk_policy.py -q
"""
from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path


# --- R1: Level-Mismatch (kind-Level != adapter-Capability) -------------------

def test_allowed_combos_pass() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # alle produktiven Kombinationen (Spec §Betriebsauswirkung)
    for kind, adapter in [("echo", "echo"), ("implement", "codex"),
                          ("test", "codex"), ("review", "claude"),
                          ("research", "claude"), ("research", "echo"),
                          ("implement", "increment")]:
        v = rp.check_task(kind, adapter, "## Ziel\nbau das Feature\n")
        assert v is None, f"{kind}/{adapter} muss erlaubt sein, got {v}"


def test_level_mismatch_rejected_both_directions() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # bauender Adapter auf read-Task (Eskalation)
    v = rp.check_task("review", "codex", "review the diff")
    assert v is not None and v.rule == "level-mismatch", v
    # read-Adapter auf build-Task (heutiges Spaet-Leise-Scheitern)
    v = rp.check_task("implement", "claude", "baue X")
    assert v is not None and v.rule == "level-mismatch", v
    # Begruendung nennt beide Seiten
    assert "implement" in v.reason and "claude" in v.reason


# --- R2: Ops-Verben im Auftragstext ------------------------------------------

def test_ops_verbs_rejected() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    ops_texts = [
        "registriere via schtasks /create einen Task",
        "fuehre Register-ScheduledTask aus",
        "Unregister-ScheduledTask -TaskName X",
        "git push origin main am Ende",
        "merge den Branch am Ende nach master",
        "nutze die ADMIN_PIN aus der Config",
        "/admin status",
    ]
    for text in ops_texts:
        v = rp.check_task("implement", "codex", text)
        assert v is not None and v.rule == "ops-verb", f"{text!r}: {v}"
        # Begruendung nennt das Pattern, aber niemals mehr als den Treffer
        assert v.reason, text


def test_harmless_texts_pass() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    ok_texts = [
        "review the scheduler docs",                       # kein Ops-Verb
        "pushe auf den bridge/task-Branch",                # kein Base-Push
        "git push origin bridge/loop-123",                 # Branch-Push ok
        "der Admin sieht das Dashboard",                   # 'admin' mitten im Wort/Satz
        "schreibe Tests fuer den task scheduler",
    ]
    for text in ok_texts:
        v = rp.check_task("implement", "codex", text)
        assert v is None, f"{text!r} darf nicht matchen: {v}"


def test_ops_scan_also_on_read_tasks() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    # R2 gilt unabhaengig vom Level — auch ein read-Task darf keine Ops anweisen
    v = rp.check_task("review", "claude", "und danach git push origin master")
    assert v is not None and v.rule == "ops-verb", v


# --- R3: fail-closed bei Drift/kaputten Eingaben ------------------------------

def test_unknown_values_fail_closed() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    for kind, adapter in [("deploy", "codex"), ("implement", "gemini"),
                          ("", "echo"), ("echo", ""), (None, "echo"),
                          ("echo", None)]:
        v = rp.check_task(kind, adapter, "x")
        assert v is not None and v.rule == "unknown-field", f"{kind}/{adapter}: {v}"


def test_none_body_is_safe() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    assert rp.check_task("echo", "echo", None) is None
    assert rp.check_task("echo", "echo", "") is None


# --- Tabellen-Invarianten ------------------------------------------------------

def test_tables_cover_levels() -> None:
    import risk_policy as rp
    importlib.reload(rp)
    assert rp.LEVELS == ("read", "build", "ops")
    # kein kind erreicht ops — 'kein Admin-Exec ueber die Bridge' strukturell
    assert "ops" not in rp.KIND_LEVEL.values()
    assert "ops" not in rp.ADAPTER_CAPABILITY.values()
    assert set(rp.KIND_LEVEL.values()) <= set(rp.LEVELS)
    assert set(rp.ADAPTER_CAPABILITY.values()) <= set(rp.LEVELS)
```

- [ ] **Step 2: Tests laufen lassen — müssen failen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: FAIL/ERROR mit `ModuleNotFoundError: No module named 'risk_policy'`

- [ ] **Step 3: `scripts/risk_policy.py` implementieren**

```python
"""Risk-Level-Policy fuer Bridge-Tasks (Spec 2026-06-12-risk-level-mapping).

Deklarative, enforced Tabelle: kind/adapter -> Risk-Level (read|build|ops).
`ops` existiert als Level, aber KEIN kind/adapter erreicht es — "kein
Admin-Exec ueber die Bridge" ist damit strukturell codiert. Drei Regeln,
fail-closed, kein Override (anders als secret_gate's --allow-secrets):

R1 level-mismatch  Adapter-Capability != Kind-Level (beide Richtungen).
R2 ops-verb        Ops-Verben im AUFTRAGSTEXT (nie im Diff — L12/Gate-vs-Gate:
                   gebaute Diffs prueft weiterhin loop_driver.scan_dangerous).
R3 unknown-field   unbekanntes kind/adapter -> wie ops = Ablehnung. Ein neuer
                   Wert zwingt zur bewussten Policy-Entscheidung hier.

Patterns liegen bewusst im Code (Vorbild loop_driver.DANGEROUS_PATTERNS),
nicht in config.json — ein Security-Gate ist nicht soft-konfigurierbar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

LEVELS = ("read", "build", "ops")

KIND_LEVEL = {
    "echo": "read", "review": "read", "research": "read",
    "implement": "build", "test": "build",
}
ADAPTER_CAPABILITY = {
    "echo": "read", "claude": "read",
    "codex": "build", "increment": "build",
}

# Ops-Verben: Scheduled-Task-Verwaltung, Push/Merge in die Base, Admin.
# Treffer im Auftragstext -> Ablehnung. Kleine, dokumentierte FP-Flaeche
# (Spec §R2): Ablehnung ist im Result sichtbar, Umformulieren moeglich.
OPS_PATTERNS = [
    r"\bschtasks\b",
    r"\b(un)?register-scheduledtask\b",
    r"\bgit\s+push\s+\S+\s+(main|master)\b",
    r"\bmerge\b.{0,40}\b(main|master)\b",
    r"\badmin_pin\b",
    r"^/admin\b",
]
_OPS_RE = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in OPS_PATTERNS]


@dataclass(frozen=True)
class Violation:
    rule: str    # "level-mismatch" | "ops-verb" | "unknown-field"
    reason: str  # menschenlesbar, landet im Result/error_text


def check_task(kind: str | None, adapter: str | None,
               body: str | None) -> Violation | None:
    """Prueft einen Task gegen die Policy. None = erlaubt.

    Wirft nie — kaputte Eingaben (None/leer/unbekannt) sind R3-Ablehnungen
    (fail-closed), kein Crash im Poller/Writer.
    """
    kind_level = KIND_LEVEL.get(kind or "")
    adapter_cap = ADAPTER_CAPABILITY.get(adapter or "")
    if kind_level is None or adapter_cap is None:
        return Violation(
            rule="unknown-field",
            reason=(f"kind={kind!r} oder adapter={adapter!r} nicht in der "
                    "Policy-Tabelle (risk_policy.py) — fail-closed"))
    if kind_level != adapter_cap:
        return Violation(
            rule="level-mismatch",
            reason=(f"kind={kind} verlangt Level {kind_level}, "
                    f"adapter={adapter} hat Capability {adapter_cap}"))
    for pat, rx in zip(OPS_PATTERNS, _OPS_RE):
        m = rx.search(body or "")
        if m:
            return Violation(
                rule="ops-verb",
                reason=(f"Ops-Verb im Auftrag ({pat}): {m.group(0)!r} — "
                        "Ops laufen nie ueber die Bridge, nur interaktiv"))
    return None
```

- [ ] **Step 4: Tests laufen lassen — müssen passen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: PASS (8 Tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/risk_policy.py scripts/test_risk_policy.py
git commit -m "feat: risk_policy module (kind/adapter -> read/build/ops, fail-closed)"
```

---

### Task 2: loop_driver-Etikett-Vorarbeit (kind=implement für bauende Runden-Tasks)

**Files:**
- Modify: `scripts/loop_driver.py:299` (in `write_round_task`)
- Test: `scripts/test_risk_policy.py` (anhängen)

**Kontext:** `write_round_task` hartkodiert `kind: "echo"` — auch wenn `adapter=codex` baut (Ping-Pong). Ohne diesen Fix lehnt Task 4 produktive Loops ab. `write_review_task` ist korrekt und bleibt unberührt.

- [ ] **Step 1: Failing Test anhängen**

An `scripts/test_risk_policy.py` anhängen:

```python
# --- loop_driver-Etikett: bauende Runden-Tasks tragen kind=implement ----------

def _fresh_bridge(endpoint: str = "claude@laptop-a") -> Path:
    root = Path(tempfile.mkdtemp(prefix="bridge-rp-"))
    os.environ["DUAL_BRIDGE_ROOT"] = str(root)
    os.environ["DUAL_BRIDGE_ENDPOINT"] = endpoint
    return root


def test_write_round_task_kind_follows_repo() -> None:
    _fresh_bridge()
    import bridge_common as bc; importlib.reload(bc)
    import loop_driver as ld; importlib.reload(ld)
    bc.ensure_dirs()
    lane = bc.send_lane()
    # bauender Runden-Task (repo gesetzt) -> implement
    tid = ld.write_round_task("loop-x", 1, "bau weiter", adapter="codex",
                              repo="https://github.com/dynamic-dome/dual-bridge",
                              base_branch="main", loop_branch="bridge/loop-x")
    fm, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_outbox(lane) / f"task-{tid}.md"))
    assert fm["kind"] == "implement", fm["kind"]
    # Text-Runde (kein repo) -> echo wie bisher
    tid2 = ld.write_round_task("loop-y", 1, "zaehle hoch", adapter="echo")
    fm2, _ = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_outbox(lane) / f"task-{tid2}.md"))
    assert fm2["kind"] == "echo", fm2["kind"]
    # beide Kombos sind policy-konform (Ping-Pong darf nicht brechen)
    import risk_policy as rp; importlib.reload(rp)
    assert rp.check_task(fm["kind"], "codex", "x") is None
    assert rp.check_task(fm2["kind"], "echo", "x") is None
```

- [ ] **Step 2: Test laufen lassen — muss failen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py::test_write_round_task_kind_follows_repo -q`
Expected: FAIL mit `assert 'echo' == 'implement'`

- [ ] **Step 3: Fix in `write_round_task`**

In `scripts/loop_driver.py`, Zeile 299, im fm-Dict von `write_round_task`:

```python
# vorher:
        "status": "open", "task_id": task_id, "kind": "echo",
# nachher (bauende Runden-Tasks tragen das ehrliche Etikett; Text-Runden echo):
        "status": "open", "task_id": task_id,
        "kind": "implement" if repo else "echo",
```

- [ ] **Step 4: Test + Goal-Loop-Regressionen laufen lassen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py test_goal_loop.py -q`
Expected: PASS (keine Regression im Loop)

- [ ] **Step 5: Commit**

```bash
git add scripts/loop_driver.py scripts/test_risk_policy.py
git commit -m "fix: write_round_task labels building round tasks kind=implement (spec Vorarbeit)"
```

---

### Task 3: Sender-Enforcement in `handoff_write` (+ choices aus der Policy)

**Files:**
- Modify: `scripts/handoff_write.py:25-45` (choices) und `:86-97` (Gate)
- Test: `scripts/test_risk_policy.py` (anhängen)

- [ ] **Step 1: Failing Tests anhängen**

```python
# --- handoff_write: Sender-Gate (kein Override) --------------------------------

def test_handoff_write_rejects_mismatch_and_ops() -> None:
    _fresh_bridge()
    import bridge_common as bc; importlib.reload(bc)
    import handoff_write as hw; importlib.reload(hw)
    bc.ensure_dirs()
    lane = bc.send_lane()
    # Level-Mismatch: review+codex -> rc 3, nichts geschrieben
    rc = hw.main(["review den diff", "--kind", "review", "--adapter", "codex"])
    assert rc == 3, rc
    assert not list(bc.lane_outbox(lane).glob("task-*.md"))
    # Ops-Verb -> rc 3, nichts geschrieben
    rc = hw.main(["git push origin main bitte", "--kind", "implement",
                  "--adapter", "codex"])
    assert rc == 3, rc
    assert not list(bc.lane_outbox(lane).glob("task-*.md"))
    # erlaubte Kombination schreibt weiterhin (rc 0)
    rc = hw.main(["spiegel mich", "--kind", "echo", "--adapter", "echo"])
    assert rc == 0, rc
    assert len(list(bc.lane_outbox(lane).glob("task-*.md"))) == 1


def test_handoff_write_choices_match_policy_tables() -> None:
    import handoff_write as hw; importlib.reload(hw)
    import risk_policy as rp; importlib.reload(rp)
    # Drift-Test (Spec §Tests Nr. 6): neue kinds/adapters ohne Policy-Eintrag
    # machen die Suite rot.
    assert hw.KIND_CHOICES == sorted(rp.KIND_LEVEL)
    assert hw.ADAPTER_CHOICES == sorted(rp.ADAPTER_CAPABILITY)
```

- [ ] **Step 2: Tests laufen lassen — müssen failen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: FAIL (`AttributeError: ... no attribute 'KIND_CHOICES'`, rc-Assertion)

- [ ] **Step 3: `handoff_write.py` anpassen**

Oben bei den Imports `import risk_policy` ergänzen, dann Modul-Konstanten vor `main()`:

```python
# Choices kommen aus der Policy-Tabelle — EINE Quelle, kein Drift (Spec §Tests 6).
KIND_CHOICES = sorted(risk_policy.KIND_LEVEL)
ADAPTER_CHOICES = sorted(risk_policy.ADAPTER_CAPABILITY)
```

In den argparse-Argumenten die Literal-Listen ersetzen:

```python
# --kind:    choices=["echo", "implement", "research", "review", "test"]
#         -> choices=KIND_CHOICES
# --adapter: choices=["echo", "codex", "claude", "increment"]
#         -> choices=ADAPTER_CHOICES
```

Nach dem Secret-Gate-Block (hinter Zeile 97, vor `out_path = ...`) das Risk-Gate einfügen — **bewusst KEIN Override-Flag** (Spec: es gibt keinen legitimen Ops-Task über die Bridge):

```python
    violation = risk_policy.check_task(args.kind, args.adapter, document)
    if violation is not None:
        print(f"[risk-policy] {violation.rule}: {violation.reason}",
              file=sys.stderr)
        print(f"[{me}] Task NICHT geschrieben — Risk-Policy-Verstoss "
              "(kein Override; Ops-Arbeit laeuft interaktiv).",
              file=sys.stderr)
        return 3
```

- [ ] **Step 4: Tests laufen lassen — müssen passen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff_write.py scripts/test_risk_policy.py
git commit -m "feat: handoff_write enforces risk policy (rc 3, no override; choices from table)"
```

---

### Task 4: Empfänger-Enforcement in `handoff_poll.process_one` (Sicherheitsgrenze)

**Files:**
- Modify: `scripts/handoff_poll.py:203-205`
- Test: `scripts/test_risk_policy.py` (anhängen)

- [ ] **Step 1: Failing Tests anhängen**

```python
# --- handoff_poll: Empfaenger-Gate (Sicherheitsgrenze) --------------------------

def _put_task(bc, lane: str, kind: str, adapter: str, body: str) -> str:
    task_id = bc.make_task_id()
    fm = {"created": bc.now_iso(), "from": "codex@laptop-b",
          "to": "claude@laptop-a", "status": "open", "task_id": task_id,
          "kind": kind, "adapter": adapter, "claimed_by": "", "claimed_at": ""}
    bc.write_text_utf8(bc.lane_outbox(lane) / f"task-{task_id}.md",
                       bc.build_document(fm, body))
    return task_id


def test_poll_rejects_policy_violation_with_error_result() -> None:
    _fresh_bridge("claude@laptop-a")  # A receives on B-to-A
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    # Level-Mismatch: review+codex — Runner darf NIE laufen
    tid = _put_task(bc, "B-to-A", "review", "codex", "## Auftrag\nbau was\n")
    task = bc.lane_outbox("B-to-A") / f"task-{tid}.md"
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{tid}.md"))
    assert rfm["status"] == "error"
    assert "risk_policy:level-mismatch" in rbody
    # Task archiviert (nichts haengt)
    assert (bc.lane_processed("B-to-A") / f"task-{tid}.claimed-{bc.DEVICE}.md").exists() \
        or list(bc.lane_processed("B-to-A").glob(f"task-{tid}*"))


def test_poll_rejects_ops_verb_in_auftrag() -> None:
    _fresh_bridge("claude@laptop-a")
    import bridge_common as bc; importlib.reload(bc)
    import runners; importlib.reload(runners)
    import handoff_poll as hp; importlib.reload(hp)
    bc.ensure_dirs()
    tid = _put_task(bc, "B-to-A", "echo", "echo",
                    "## Auftrag\nschtasks /create /tn evil\n")
    task = bc.lane_outbox("B-to-A") / f"task-{tid}.md"
    assert hp.process_one(task, lane="B-to-A") is True
    rfm, rbody = bc.parse_frontmatter(
        bc.read_text_utf8(bc.lane_inbox("B-to-A") / f"result-{tid}.md"))
    assert rfm["status"] == "error"
    assert "risk_policy:ops-verb" in rbody
```

- [ ] **Step 2: Tests laufen lassen — müssen failen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: FAIL (Result hat `status: done`, echo-Runner lief)

- [ ] **Step 3: Gate in `process_one` einbauen**

In `scripts/handoff_poll.py` oben `import risk_policy` ergänzen. Dann den Dispatch (Zeile 203-214) umbauen — Violation ersetzt den Runner-Lauf, fließt in den BESTEHENDEN Result-/Archiv-Pfad (no stuck, no silent failure):

```python
    auftrag = _extract_section(body, "## Auftrag") or body.strip()
    adapter = fm.get("adapter", "echo")
    violation = risk_policy.check_task(fm.get("kind", "echo"), adapter, auftrag)
    if violation is not None:
        result = runners.RunnerResult(
            status="error",
            error_text=f"risk_policy:{violation.rule}: {violation.reason}")
    else:
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
```

(Der `unbekannter adapter`-Zweig bleibt als Defense-in-Depth — R3 fängt ihn schon vorher, aber der Registry-Check kostet nichts.)

- [ ] **Step 4: Tests + Lane-Regressionen laufen lassen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py test_lanes.py -q`
Expected: PASS (test_lanes nutzt research/echo + review/claude — beides policy-konform)

- [ ] **Step 5: Commit**

```bash
git add scripts/handoff_poll.py scripts/test_risk_policy.py
git commit -m "feat: handoff_poll enforces risk policy at the claim boundary (error result, archived)"
```

---

### Task 5: DCO-Pfad-Enforcement in `job_poll.process_item`

**Files:**
- Modify: `scripts/job_poll.py:267-272`
- Test: `scripts/test_risk_policy.py` (anhängen)

- [ ] **Step 1: Failing Tests anhängen**

```python
# --- job_poll: DCO-Pfad (Seed-Check vor Loop-Start) ----------------------------

class _FakeItem:
    job_id = "j-1"
    def __init__(self, text: str) -> None:
        self.input_text = text


def test_job_poll_rejects_ops_seed_rc2_todo_stays_open() -> None:
    import job_poll as jp; importlib.reload(jp)
    calls = []
    def fake_run(**kw):  # darf NIE erreicht werden
        calls.append(kw)
        return {"exit": 0}
    out = {}
    rc = jp.process_item(
        _FakeItem("repo=https://github.com/dynamic-dome/dual-bridge\n"
                  "registriere das per Register-ScheduledTask"),
        run_fn=fake_run, out_payload=out)
    assert rc == 2, rc                      # Config-Klasse: Todo bleibt offen
    assert "risk_policy:ops-verb" in out.get("error", ""), out
    assert calls == [], "run_fn darf bei Policy-Verstoss nicht laufen"


def test_job_poll_clean_seed_still_runs() -> None:
    import job_poll as jp; importlib.reload(jp)
    def fake_run(**kw):
        return {"exit": 0}
    rc = jp.process_item(
        _FakeItem("repo=https://github.com/dynamic-dome/dual-bridge\n"
                  "baue ein kleines Feature"),
        run_fn=fake_run)
    assert rc == 0, rc
```

- [ ] **Step 2: Tests laufen lassen — müssen failen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py -q`
Expected: FAIL (rc == 0 statt 2, fake_run lief)

- [ ] **Step 3: Gate in `process_item` einbauen**

In `scripts/job_poll.py` oben `import risk_policy` ergänzen. In `process_item` direkt nach dem `parsed.repo is None`-Block (Zeile 271) einfügen:

```python
    violation = risk_policy.check_task(parsed.kind, parsed.adapter, parsed.seed)
    if violation is not None:
        if out_payload is not None:
            out_payload["error"] = (
                f"risk_policy:{violation.rule}: {violation.reason} (rc 2)")
        return 2
```

(rc 2 = Config-Fehler-Klasse wie `seed ohne repo=` — der DCO lässt das Todo offen, kein Retry-Sturm, Spec §Enforcement.)

- [ ] **Step 4: Tests + job_poll-Regressionen laufen lassen**

Run: `cd scripts && python -X utf8 -m pytest test_risk_policy.py test_job_poll.py -q`
Expected: PASS (Default-Parse ist kind=implement/adapter=codex → policy-konform)

- [ ] **Step 5: Commit**

```bash
git add scripts/job_poll.py scripts/test_risk_policy.py
git commit -m "feat: job_poll checks risk policy before loop start (rc 2, todo stays open)"
```

---

### Task 6: Volle Suite + Doku

**Files:**
- Modify: `README.md` (Härtung-Sektion + Test-Soll-Zahl)
- Modify: `HOW-TO-USE.md` (nur falls dort eine Test-Soll-Zahl steht)

- [ ] **Step 1: Volle Suite laufen lassen**

Run: `cd scripts && python -X utf8 -m pytest -q`
Expected: PASS, Zahl = 380 + neue Tests (~11) = ~391. KEINE Failures. Bei unerwarteten Failures: superpowers:systematic-debugging, nicht blind fixen.

- [ ] **Step 2: README ergänzen**

In `README.md` die Härtung-/Sicherheits-Sektion finden (`grep -n "Härtung\|Secrets" README.md`) und diesen Absatz ergänzen (an die bestehende Stilebene anpassen):

```markdown
### Risk-Level-Policy (kind/adapter → read/build/ops)

`scripts/risk_policy.py` erzwingt eine deklarative Policy: jedes Task-`kind`
hat ein Risk-Level (`echo`/`review`/`research` → read, `implement`/`test` →
build), jeder `adapter` eine Capability. `ops` (Scheduled Tasks, Push/Merge in
die Base, Admin) erreicht kein kind — Ops-Arbeit läuft nie über die Bridge,
nur interaktiv. Geprüft fail-closed an drei Punkten: `handoff_write` (rc 3,
kein Override), `handoff_poll` (Error-Result, Task archiviert) und `job_poll`
(rc 2, Todo bleibt offen). Zusätzlich scannt R2 den AUFTRAGSTEXT auf
Ops-Verben (`schtasks`, `Register-ScheduledTask`, Push/Merge auf main/master,
Admin-PIN) — bewusst NICHT den gebauten Diff (Gate-vs-Gate, Lehre L12).
Unbekannte kind/adapter-Werte werden abgelehnt (R3); neue Werte brauchen
einen bewussten Eintrag in der Policy-Tabelle.
Spec: `docs/superpowers/specs/2026-06-12-risk-level-mapping-design.md`.
```

Test-Soll-Zahl in README (und HOW-TO-USE.md, falls dort genannt) auf die neue Zahl aus Step 1 aktualisieren (`grep -n "380" README.md HOW-TO-USE.md`).

- [ ] **Step 3: Commit**

```bash
git add README.md HOW-TO-USE.md
git commit -m "docs: risk-level policy section + test count"
```

---

## Selbst-Review-Notizen (Spec-Abdeckung)

- Spec §Skala/§Komponente → Task 1. §Vorarbeit → Task 2. §Enforcement (3 Punkte) → Tasks 3-5. §Tests 1-3 → Task 1, §Tests 4 → Task 4, §Tests 5 → Task 3, §Tests 6 (Drift) → Task 3 (`KIND_CHOICES`-Assertion, strukturell durch choices-aus-Tabelle). §Fehlerbehandlung → check_task wirft nie (Task 1 R3-Tests) + bestehende Result-Pfade (Task 4/5).
- R1 nutzt `!=` (Gleichheit gefordert), deckt damit beide Spec-Richtungen ab.
- `_put_task`-Archiv-Assertion ist bewusst tolerant (glob), weil der Claimed-Dateiname das Claim-Suffix trägt.
