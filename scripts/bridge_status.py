"""Read-only Bridge-Status-Dashboard für dual-bridge.

Eine reine Lese-Linse über den Bridge-Baum: zählt offene/geclaimte/erledigte
Tasks pro Lane, rekonstruiert Loop-Verläufe aus den LOOP-*.jsonl-Historien,
hebt offene Eskalationen und _errors/-Quarantäne hervor und prüft die Liveness
des Pollers über dessen Lock-Datei.

INVARIANTE: Dieses Skript schreibt, claimt oder verschiebt NIE etwas. Es liest
nur und rendert. Alle Lesezugriffe sind defensiv ("never crash") — ein halb
geschriebenes File oder eine kaputte JSONL-Zeile darf die Gesamtsicht nie
zerreißen.

Dual-runnable wie der Rest der Suite:
    python -m pytest scripts/test_bridge_status.py
    python scripts/bridge_status.py [--format text|json] [--watch [--interval N]] [--lane <lane>]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import bridge_common as bc


def _resolve_state_dir() -> Path:
    """Loop-State liegt A-seitig in scripts/state/ (wie loop_driver.STATE_DIR).

    DUAL_BRIDGE_STATE überschreibt den Pfad — das nutzen die Tests, um den
    State-Ordner hermetisch in ein tmp-Verzeichnis zu isolieren (der State liegt
    bewusst NICHT unter DUAL_BRIDGE_ROOT, da es ein lokaler, kein Drive-Pfad
    ist). Wird bei jedem importlib.reload(bs) neu ausgewertet.
    """
    override = os.environ.get("DUAL_BRIDGE_STATE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "state"


STATE_DIR = _resolve_state_dir()


# --- Datentypen --------------------------------------------------------------
@dataclass
class TaskInfo:
    """Eine Task-/Result-Datei, reduziert auf die fürs Dashboard nötigen Felder."""
    task_id: str = ""
    name: str = ""
    status: str = ""
    kind: str = ""
    adapter: str = ""
    created: str = ""
    loop_id: str = ""
    round: str = ""
    verdict: str = ""
    claimed_device: str = ""


@dataclass
class LaneStatus:
    lane: str = ""
    open: list = field(default_factory=list)
    claimed: list = field(default_factory=list)
    results: list = field(default_factory=list)
    processed_count: int = 0
    errors_count: int = 0
    conflicts_count: int = 0
    incomplete_count: int = 0


@dataclass
class LoopStatus:
    loop_id: str = ""
    last_round: int = -1
    last_verdict: str = ""
    last_commit: str = ""
    state: str = "running"  # running | accepted | escalated | aborted
    escalation_trigger: str = ""


@dataclass
class EscalationInfo:
    loop_id: str = ""
    trigger: str = ""
    round: str = ""
    branch: str = ""
    commit: str = ""
    created: str = ""


@dataclass
class LivenessStatus:
    label: str = ""
    running: bool = False
    pid: int = 0
    timestamp: str = ""
    present: bool = False  # Lock-Datei existiert überhaupt?


@dataclass
class Report:
    lanes: list = field(default_factory=list)
    loops: list = field(default_factory=list)
    escalations: list = field(default_factory=list)
    errors: list = field(default_factory=list)  # (lane, name)-Quarantäne-Liste
    liveness: list = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# --- defensive Helfer --------------------------------------------------------
def _is_conflict_copy(name: str) -> bool:
    """Drive-Konfliktkopien tragen ein '(n)' im Namen, z.B. 'task-x (1).md'.

    Nutzt bc._is_conflict_copy falls vorhanden, sonst dieselbe Heuristik.
    """
    fn = getattr(bc, "_is_conflict_copy", None)
    if callable(fn):
        try:
            return bool(fn(name))
        except Exception:  # noqa: BLE001 — Heuristik darf nie crashen
            pass
    return "(" in name and ")" in name


def _safe_frontmatter(path: Path) -> dict:
    """Frontmatter lesen, ohne je zu crashen. {} bei jedem Problem."""
    try:
        fm, _ = bc.parse_frontmatter(bc.read_text_utf8(path))
        return fm
    except Exception:  # noqa: BLE001
        return {}


def _task_from_file(path: Path) -> TaskInfo:
    fm = _safe_frontmatter(path)
    return TaskInfo(
        task_id=fm.get("task_id", ""),
        name=path.name,
        status=fm.get("status", ""),
        kind=fm.get("kind", ""),
        adapter=fm.get("adapter", ""),
        created=fm.get("created", ""),
        loop_id=fm.get("loop_id", ""),
        round=fm.get("round", ""),
        verdict=fm.get("verdict", ""),
        claimed_device=_device_from_name(path.name),
    )


def _device_from_name(name: str) -> str:
    """Aus 'task-<id>.claimed-<device>-<claimid>.md' das Device extrahieren."""
    if ".claimed-" not in name:
        return ""
    rest = name.split(".claimed-", 1)[1]
    # rest == '<device>-<claimid>.md' — claimid ist das letzte '-'-Segment.
    rest = rest[:-3] if rest.endswith(".md") else rest
    if "-" in rest:
        return rest.rsplit("-", 1)[0]
    return rest


def _count_files(directory: Path) -> int:
    try:
        return sum(1 for p in directory.iterdir() if p.is_file())
    except (FileNotFoundError, NotADirectoryError, OSError):
        return 0


# --- Scanner ----------------------------------------------------------------
def scan_lane(lane: str) -> LaneStatus:
    """Eine Lane lesen: outbox (open/claimed/incomplete/conflicts), inbox
    (results) sowie _processed/ + _errors/-Zähler. Mutiert nichts."""
    st = LaneStatus(lane=lane)

    outbox = bc.lane_outbox(lane)
    try:
        entries = sorted(p for p in outbox.iterdir() if p.is_file())
    except (FileNotFoundError, NotADirectoryError, OSError):
        entries = []

    for p in entries:
        name = p.name
        if not name.startswith("task-"):
            continue
        if _is_conflict_copy(name):
            st.conflicts_count += 1
            continue
        info = _task_from_file(p)
        if not info.task_id:
            # Halb geschriebenes File (kein task_id) — niemals ein valider Task.
            st.incomplete_count += 1
            continue
        if ".claimed-" in name:
            st.claimed.append(info)
        else:
            st.open.append(info)

    inbox = bc.lane_inbox(lane)
    try:
        results = sorted(p for p in inbox.iterdir() if p.is_file())
    except (FileNotFoundError, NotADirectoryError, OSError):
        results = []
    for p in results:
        if not p.name.startswith("result-"):
            continue
        if _is_conflict_copy(p.name):
            st.conflicts_count += 1
            continue
        st.results.append(_task_from_file(p))

    st.processed_count = _count_files(bc.lane_processed(lane))
    st.errors_count = _count_files(bc.lane_errors(lane))
    return st


def scan_loops(state_dir: Path) -> list:
    """Loop-Historien aus LOOP-*.jsonl rekonstruieren. Append-only: die letzte
    gültige Zeile ist der aktuelle Stand. Eine kaputte JSONL-Zeile wird
    übersprungen, nicht fatal. ESCALATION-<id>.md hebt den Zustand auf
    'escalated' und liefert den Trigger."""
    loops: list[LoopStatus] = []
    try:
        files = sorted(state_dir.glob("LOOP-*.jsonl"))
    except OSError:
        files = []

    for path in files:
        loop_id = path.name[len("LOOP-"):-len(".jsonl")]
        last: dict = {}
        try:
            raw = bc.read_text_utf8(path)
        except Exception:  # noqa: BLE001
            raw = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue  # kaputte Zeile tolerieren
            if isinstance(rec, dict):
                last = rec

        lp = LoopStatus(loop_id=loop_id)
        if last:
            try:
                lp.last_round = int(last.get("round", -1))
            except (ValueError, TypeError):
                lp.last_round = -1
            lp.last_verdict = str(last.get("verdict") or "")
            lp.last_commit = str(last.get("commit") or "")
            if lp.last_verdict == "accepted":
                lp.state = "accepted"
            elif lp.last_verdict in ("aborted", "abort"):
                lp.state = "aborted"
            else:
                lp.state = "running"

        # Eskalations-Datei überschreibt den Zustand.
        esc_path = state_dir / f"ESCALATION-{loop_id}.md"
        if esc_path.exists():
            lp.state = "escalated"
            fm = _safe_frontmatter(esc_path)
            lp.escalation_trigger = fm.get("trigger", "")
        loops.append(lp)
    return loops


def scan_escalations(state_dir: Path) -> list:
    """Offene Eskalationen aus state_dir/ESCALATION-*.md lesen. _processed/
    wird bewusst ignoriert (das sind bereits abgearbeitete Eskalationen)."""
    out: list[EscalationInfo] = []
    try:
        files = sorted(state_dir.glob("ESCALATION-*.md"))
    except OSError:
        files = []
    for path in files:
        fm = _safe_frontmatter(path)
        loop_id = fm.get("loop_id") or path.name[len("ESCALATION-"):-len(".md")]
        out.append(EscalationInfo(
            loop_id=loop_id,
            trigger=fm.get("trigger", ""),
            round=fm.get("round", ""),
            branch=fm.get("branch", ""),
            commit=fm.get("commit", ""),
            created=fm.get("created", ""),
        ))
    return out


def scan_lock(lock_path: Path, label: str = "poller",
              must_match: str | None = None) -> LivenessStatus:
    """Liveness aus einer Lock-Datei lesen (Format: 'pid\\ntimestamp\\n').
    Liveness des PID über bc._pid_alive. must_match (z.B. 'handoff_poll') stellt
    sicher, dass eine recycelte Fremd-PID nicht als laufender Poller gilt (L11).
    Mutiert nichts."""
    ls = LivenessStatus(label=label)
    try:
        if not lock_path.exists():
            return ls
        ls.present = True
        content = bc.read_text_utf8(lock_path)
    except Exception:  # noqa: BLE001
        return ls
    lines = content.splitlines()
    if lines:
        try:
            ls.pid = int(lines[0].strip())
        except (ValueError, IndexError):
            ls.pid = 0
    if len(lines) > 1:
        ls.timestamp = lines[1].strip()
    if ls.pid > 0:
        try:
            ls.running = bool(bc._pid_alive(ls.pid, must_match=must_match))
        except Exception:  # noqa: BLE001
            ls.running = False
    return ls


# --- Report-Aufbau -----------------------------------------------------------
def _all_lanes() -> list:
    """Alle bekannten Lanes (Sende-Lanes beider Endpoints), dedupliziert."""
    lanes = []
    for cfg in bc.ENDPOINTS.values():
        lane = cfg.get("sends_on")
        if lane and lane not in lanes:
            lanes.append(lane)
    if not lanes:
        lanes = ["A-to-B", "B-to-A"]
    return lanes


def build_report(lanes: list | None = None, state_dir: Path | None = None) -> Report:
    """Vollständigen Read-Only-Snapshot bauen: alle Lanes + Loops + Eskalationen
    + Liveness. Schreibt nichts (rein lesend)."""
    state_dir = state_dir or STATE_DIR
    lanes = lanes if lanes is not None else _all_lanes()

    rep = Report()
    rep.lanes = [scan_lane(lane) for lane in lanes]
    rep.loops = scan_loops(state_dir)
    rep.escalations = scan_escalations(state_dir)

    # _errors/-Quarantäne als prominente flache Liste sammeln.
    for ls in rep.lanes:
        errs = bc.lane_errors(ls.lane)
        try:
            for p in sorted(errs.iterdir()):
                if p.is_file():
                    rep.errors.append({"lane": ls.lane, "name": p.name})
        except (FileNotFoundError, NotADirectoryError, OSError):
            pass

    # Liveness: Poller-Lock (lazily, read-only — kein Anlegen).
    try:
        lock = bc.default_lock_path()
        rep.liveness = [scan_lock(lock, label="poller", must_match="handoff_poll")]
    except Exception:  # noqa: BLE001
        rep.liveness = []

    rep.summary = {
        "open": sum(len(l.open) for l in rep.lanes),
        "claimed": sum(len(l.claimed) for l in rep.lanes),
        "results": sum(len(l.results) for l in rep.lanes),
        "processed": sum(l.processed_count for l in rep.lanes),
        "errors": sum(l.errors_count for l in rep.lanes),
        "conflicts": sum(l.conflicts_count for l in rep.lanes),
        "incomplete": sum(l.incomplete_count for l in rep.lanes),
        "loops": len(rep.loops),
        "escalations": len(rep.escalations),
    }
    return rep


# --- Rendering ---------------------------------------------------------------
def render_json(report: Report) -> str:
    """Report als valides JSON. Top-Level-Keys: escalations, errors, loops,
    lanes, liveness, summary."""
    payload = {
        "escalations": [dataclasses.asdict(e) for e in report.escalations],
        "errors": list(report.errors),
        "loops": [dataclasses.asdict(l) for l in report.loops],
        "lanes": [dataclasses.asdict(l) for l in report.lanes],
        "liveness": [dataclasses.asdict(l) for l in report.liveness],
        "summary": dict(report.summary),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_text(report: Report) -> str:
    """Report als Klartext. Dringlichkeitsreihenfolge: ESKALATIONEN und
    _errors-Quarantäne ZUERST, dann die Lane-Tabellen, dann Loops + Liveness.
    Leerer Baum -> ruhiger, nicht-leerer 'alles still'-Report."""
    lines: list[str] = []
    s = report.summary
    lines.append("=== dual-bridge Status ===")
    lines.append(
        f"offen={s.get('open', 0)}  geclaimt={s.get('claimed', 0)}  "
        f"results={s.get('results', 0)}  processed={s.get('processed', 0)}  "
        f"errors={s.get('errors', 0)}  loops={s.get('loops', 0)}  "
        f"eskalationen={s.get('escalations', 0)}"
    )
    lines.append("")

    # 1) ESKALATIONEN (dringendste Stufe) zuerst.
    if report.escalations:
        lines.append("!! ESKALATIONEN (offen) !!")
        for e in report.escalations:
            lines.append(
                f"  - {e.loop_id}  trigger={e.trigger or '?'}  "
                f"round={e.round or '?'}  branch={e.branch or '?'}  "
                f"commit={e.commit or '?'}"
            )
        lines.append("")

    # 2) _errors/-Quarantäne (zweit-dringendste Stufe).
    if report.errors:
        lines.append("!! _errors/ Quarantäne !!")
        for err in report.errors:
            lines.append(f"  - [{err['lane']}] {err['name']}")
        lines.append("")

    # 3) Lane-Tabellen (Normalbetrieb).
    for ls in report.lanes:
        lines.append(f"--- lane-{ls.lane} ---")
        lines.append(
            f"  open={len(ls.open)}  claimed={len(ls.claimed)}  "
            f"results={len(ls.results)}  processed={ls.processed_count}  "
            f"errors={ls.errors_count}  conflicts={ls.conflicts_count}  "
            f"incomplete={ls.incomplete_count}"
        )
        for t in ls.open:
            lines.append(f"    open    {t.task_id}  kind={t.kind}  adapter={t.adapter}")
        for t in ls.claimed:
            lines.append(
                f"    claimed {t.task_id}  von={t.claimed_device or '?'}  kind={t.kind}"
            )
        for t in ls.results:
            lines.append(
                f"    result  {t.task_id}  verdict={t.verdict or t.status or '?'}"
            )
        lines.append("")

    # 4) Loops.
    if report.loops:
        lines.append("--- loops ---")
        for lp in report.loops:
            extra = f"  trigger={lp.escalation_trigger}" if lp.escalation_trigger else ""
            lines.append(
                f"  {lp.loop_id}  round={lp.last_round}  "
                f"verdict={lp.last_verdict or '-'}  state={lp.state}"
                f"  commit={lp.last_commit or '-'}{extra}"
            )
        lines.append("")

    # 5) Liveness.
    if report.liveness:
        lines.append("--- liveness ---")
        for lv in report.liveness:
            if not lv.present:
                state = "kein Lock (Poller nicht gestartet?)"
            elif lv.running:
                state = f"LÄUFT (pid={lv.pid})"
            else:
                state = f"TOT (pid={lv.pid} nicht aktiv)"
            lines.append(f"  {lv.label}: {state}")
        lines.append("")

    if not (report.escalations or report.errors or report.summary.get("open")
            or report.summary.get("claimed") or report.summary.get("loops")):
        lines.append("Alles ruhig — keine offenen Tasks, Loops oder Eskalationen.")

    return "\n".join(lines).rstrip("\n") + "\n"


# --- CLI ---------------------------------------------------------------------
def _parse_args(argv: list | None):
    p = argparse.ArgumentParser(
        description="Read-only Status-Dashboard für dual-bridge."
    )
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--lane", default=None,
                   help="Nur diese Lane (Default: alle bekannten Lanes).")
    p.add_argument("--watch", action="store_true",
                   help="Periodisch neu rendern (read-only, kein Lock).")
    p.add_argument("--interval", type=float, default=3.0,
                   help="Sekunden zwischen Watch-Refreshes (Default 3).")
    return p.parse_args(argv)


def _render_once(fmt: str, lanes: list | None) -> str:
    rep = build_report(lanes=lanes)
    return render_json(rep) if fmt == "json" else render_text(rep)


def main(argv: list | None = None) -> int:
    args = _parse_args(argv)
    lanes = [args.lane] if args.lane else None

    if args.watch:
        try:
            while True:
                out = _render_once(args.format, lanes)
                # Bildschirm löschen (ANSI) für eine ruhige Live-View.
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.write(out)
                sys.stdout.flush()
                time.sleep(max(0.5, args.interval))
        except KeyboardInterrupt:
            return 0
    else:
        print(_render_once(args.format, lanes))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
