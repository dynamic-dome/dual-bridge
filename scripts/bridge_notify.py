"""Eskalations-Notifier für dual-bridge — pusht neue Eskalationen per Telegram.

Push-Kante über den Eskalations-Artefakten: liest die offenen
state/ESCALATION-*.md (via bridge_status.scan_escalations), schickt für jede
NEUE eine Telegram-Nachricht und merkt sich Gesendetes ausschließlich in einem
eigenen Sidecar state/_notify/sent.json.

INVARIANTE: ändert den Loop-/Bridge-Zustand NICHT. Claimt keine Tasks,
verschiebt keine Eskalationen, schreibt nie in ESCALATION-*.md oder die Lanes —
nur in state/_notify/. Damit beliebig oft gefahrlos ausführbar (idempotent über
sent.json), genau wie das read-only Dashboard.

Self-contained, aber DCO-ready: die Versand-Logik liegt in
notify_new_escalations(); der Aufrufer (heute ein OS-Task, später optional DCO)
ist austauschbar, ohne eine Zeile hier zu ändern.

Dual-runnable:
    python -m pytest scripts/test_bridge_notify.py
    python bridge_notify.py [--dry-run] [--digest] [--reconcile]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import bridge_common as bc
import bridge_status as bs

# Sidecar-State des Notifiers (sein EINZIGER Schreib-Ort).
NOTIFY_DIR_NAME = "_notify"
SENT_FILE_NAME = "sent.json"

# Telegram-API-Timeout (Sekunden) — kurz halten, der Trigger ist ein Ein-Schuss.
_HTTP_TIMEOUT = 15


# --- Konfiguration -----------------------------------------------------------
def _telegram_config() -> tuple[str, str]:
    """(token, chat_id) aus der Env. Erste gesetzte Variable gewinnt:
    DUAL_BRIDGE_TG_* (Override) > TELEGRAM_* (DCO-geteilte Quelle).
    Leere Strings, wenn nichts konfiguriert ist (-> 'nicht konfiguriert')."""
    token = (os.environ.get("DUAL_BRIDGE_TG_TOKEN")
             or os.environ.get("TELEGRAM_TOKEN") or "").strip()
    chat = (os.environ.get("DUAL_BRIDGE_TG_CHAT")
            or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    return token, chat


def _is_configured() -> bool:
    token, chat = _telegram_config()
    return bool(token and chat)


# --- Sidecar-State (sent.json) ----------------------------------------------
def _notify_dir() -> Path:
    return bs.STATE_DIR / NOTIFY_DIR_NAME


def _sent_path() -> Path:
    return _notify_dir() / SENT_FILE_NAME


def _load_sent() -> dict:
    """Gemeldete loop_ids -> meta. Defensiv: {} bei fehlend/kaputt (nie crashen)."""
    path = _sent_path()
    try:
        if not path.exists():
            return {}
        data = json.loads(bc.read_text_utf8(path))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_sent(data: dict) -> None:
    """sent.json atomar schreiben (read-modify-write-sicher). Nur hier wird der
    Notifier-State persistiert — niemals in den Eskalations-Artefakten."""
    _notify_dir().mkdir(parents=True, exist_ok=True)
    bc.write_text_atomic(_sent_path(), json.dumps(data, ensure_ascii=False, indent=2))


# --- Telegram-Transport ------------------------------------------------------
def _post_telegram(text: str) -> None:
    """Eine Nachricht an Telegram senden. Wirft bei Fehler (Config/HTTP/Netz),
    damit der Aufrufer die Eskalation NICHT als gesendet markiert."""
    token, chat = _telegram_config()
    if not (token and chat):
        raise RuntimeError("Telegram nicht konfiguriert (TELEGRAM_TOKEN/TELEGRAM_CHAT_ID).")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    obj = json.loads(body)
    if not obj.get("ok"):
        raise RuntimeError(f"Telegram-API meldete Fehler: {body}")


# --- Nachrichten-Aufbau ------------------------------------------------------
def _escape_md(text: str) -> str:
    """Telegram-Markdown-Spezialzeichen entschärfen, damit ein bösartiger
    Eskalations-Inhalt das Markup nicht kapern kann."""
    out = []
    for ch in text:
        if ch in "_*`[]":
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _extract_question(loop_id: str, max_len: int = 400) -> str:
    """Die '## Offene Frage an den Owner' aus der ESCALATION-<loop_id>.md ziehen.
    Defensiv: leerer String, wenn nichts gefunden / nicht lesbar."""
    path = bs.STATE_DIR / f"ESCALATION-{loop_id}.md"
    try:
        _fm, body = bc.parse_frontmatter(bc.read_text_utf8(path))
    except Exception:  # noqa: BLE001
        return ""
    marker = "## Offene Frage an den Owner"
    if marker not in body:
        return ""
    after = body.split(marker, 1)[1]
    # bis zum nächsten H2-Abschnitt
    chunk = after.split("\n## ", 1)[0].strip()
    if len(chunk) > max_len:
        chunk = chunk[:max_len].rstrip() + "…"
    return chunk


def format_escalation_message(info, question: str = "") -> str:
    """Knappe, mobil lesbare Telegram-Nachricht für eine Eskalation. Alle
    free-text-Teile werden Markdown-escaped (Injection-Schutz)."""
    q = _escape_md(question) if question else "_(keine Frage hinterlegt)_"
    if not question:
        q = "(keine Frage hinterlegt)"
    lines = [
        "🚨 *dual-bridge Eskalation*",
        f"Loop: {_escape_md(info.loop_id)}",
        f"Trigger: {_escape_md(info.trigger or '?')}  (Runde {_escape_md(info.round or '?')})",
        f"Branch: {_escape_md(info.branch or '?')} @ {_escape_md(info.commit or '?')}",
        f"Frage: {q}",
        f"Seit: {_escape_md(info.created or '?')}",
    ]
    return "\n".join(lines)


def build_digest_message() -> str:
    """Tages-Zusammenfassung aus dem Dashboard-Summary (open/claimed/…)."""
    rep = bs.build_report()
    s = rep.summary
    poller = "?"
    if rep.liveness:
        lv = rep.liveness[0]
        poller = "läuft" if lv.running else ("tot" if lv.present else "aus")
    return (
        "📊 *dual-bridge Status*\n"
        f"offen: {s.get('open', 0)}  geclaimt: {s.get('claimed', 0)}  "
        f"results: {s.get('results', 0)}\n"
        f"processed: {s.get('processed', 0)}  errors: {s.get('errors', 0)}  "
        f"konflikte: {s.get('conflicts', 0)}\n"
        f"loops: {s.get('loops', 0)}  eskalationen: {s.get('escalations', 0)}\n"
        f"Poller: {poller}"
    )


# --- Kernlogik (DCO-ready: reiner Aufruf, austauschbarer Aufrufer) -----------
def notify_new_escalations(send_fn=None, dry_run: bool = False,
                           mark: bool = True) -> tuple[list, list]:
    """Für jede NEUE offene Eskalation genau eine Nachricht senden.

    send_fn: Sender (text)->None; Default _post_telegram. Im Test injiziert.
    dry_run: nichts senden, nichts markieren — nur die geplanten Nachrichten
             auf stdout zeigen.
    Rückgabe: (sent_loop_ids, failed_loop_ids).

    at-least-once: Ein Sendefehler markiert die betroffene Eskalation NICHT als
    gesendet → der nächste Lauf versucht sie erneut. Ein Fehler bei einer
    Eskalation blockiert die anderen nicht.
    """
    send_fn = send_fn or _post_telegram
    escalations = bs.scan_escalations(bs.STATE_DIR)
    already = _load_sent()

    sent: list[str] = []
    failed: list[str] = []
    new_marks: dict = {}

    for info in escalations:
        lid = info.loop_id
        if lid in already:
            continue  # schon gemeldet -> Idempotenz
        question = _extract_question(lid)
        msg = format_escalation_message(info, question)
        if dry_run:
            print(f"[dry-run] würde senden:\n{msg}\n")
            continue
        try:
            send_fn(msg)
        except Exception as exc:  # noqa: BLE001 — fail-safe, nicht markieren
            print(f"[notify] Senden fehlgeschlagen für {lid}: {exc}")
            failed.append(lid)
            continue
        sent.append(lid)
        new_marks[lid] = {"created": info.created, "notified_at": bc.now_iso()}

    if mark and not dry_run and new_marks:
        merged = _load_sent()
        merged.update(new_marks)
        _save_sent(merged)

    return sent, failed


def send_digest(send_fn=None) -> int:
    """Eine Status-Zusammenfassung senden. Rückgabe: Anzahl gesendeter
    Nachrichten (0 bei Fehler)."""
    send_fn = send_fn or _post_telegram
    msg = build_digest_message()
    try:
        send_fn(msg)
    except Exception as exc:  # noqa: BLE001
        print(f"[notify] Digest-Versand fehlgeschlagen: {exc}")
        return 0
    return 1


def reconcile() -> list:
    """sent.json gegen die aktuell offenen Eskalationen bereinigen: Einträge,
    deren Eskalation nicht mehr offen ist, entfernen. Sendet nichts. Rückgabe:
    Liste der entfernten loop_ids."""
    open_ids = {e.loop_id for e in bs.scan_escalations(bs.STATE_DIR)}
    saved = _load_sent()
    removed = [lid for lid in saved if lid not in open_ids]
    if removed:
        for lid in removed:
            saved.pop(lid, None)
        _save_sent(saved)
    return removed


# --- CLI ---------------------------------------------------------------------
def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Eskalations-Notifier für dual-bridge (Telegram, read-only auf den Artefakten)."
    )
    p.add_argument("--dry-run", action="store_true",
                   help="Nur zeigen, was gesendet würde; NICHTS senden, NICHTS markieren.")
    p.add_argument("--digest", action="store_true",
                   help="Zusätzlich eine Status-Zusammenfassung senden.")
    p.add_argument("--reconcile", action="store_true",
                   help="sent.json gegen offene Eskalationen bereinigen (kein Versand).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)

    if args.reconcile:
        removed = reconcile()
        print(f"[notify] reconcile: {len(removed)} veraltete Einträge entfernt.")
        return 0

    # Versand-Pfade brauchen Konfiguration (außer dry-run, das nichts sendet).
    if not args.dry_run and not _is_configured():
        print("[notify] Telegram nicht konfiguriert: TELEGRAM_TOKEN/TELEGRAM_CHAT_ID "
              "(oder DUAL_BRIDGE_TG_TOKEN/DUAL_BRIDGE_TG_CHAT) fehlen. Kein Versand.",
              file=sys.stderr)
        return 2

    sent, failed = notify_new_escalations(dry_run=args.dry_run)
    if not args.dry_run:
        print(f"[notify] {len(sent)} neue Eskalation(en) gemeldet, "
              f"{len(failed)} fehlgeschlagen.")

    digest_rc = 0
    if args.digest and not args.dry_run:
        n = send_digest()
        if n == 0:
            digest_rc = 3

    if failed:
        return 3
    return digest_rc


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
