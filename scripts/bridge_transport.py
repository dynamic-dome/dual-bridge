"""Transport-Abstraktion für Bridge-Jobs — WOHER kommt ein Auftrag?

Diese Schicht entkoppelt den Worker von der Herkunft eines Jobs. Heute lebt die
ganze Bridge auf der Datei/Lane-Welt (Claim via ``os.rename`` über Google Drive);
mit dem DCO-Job-Pull (Design-Spec 2026-06-04) kommt ein zweiter, gleichwertiger
Weg dazu: HTTP-Pull über die ``jobs``-Tabelle des DCO.

Beide Quellen liefern denselben **WorkItem**-Vertrag (``job_id`` + ``input_text``),
damit die Run-/Publish-Logik dahinter (loop_driver/Adapter, Exit-Mapping) komplett
identisch bleibt — derselbe injizierbarer-Caller-Trick wie ``run_fn``/``send_fn``
beim Notifier und Overnight-Scheduler.

Treiberwahl per Umgebung (additiv, rückwärtskompatibel):

    DUAL_BRIDGE_TRANSPORT = file | http      (Default: file)
    DCO_BRIDGE_URL        = http://127.0.0.1:8787
    DCO_BRIDGE_TOKEN      = <bearer-token-des-workers>
    DUAL_BRIDGE_WORKER_TYPE = dual-bridge    (Default)

Sicherheit (siehe MCP-Dossiers): HttpSource schickt den Token nur als Bearer-Header
(nie im Job-Payload). ``get_source`` ist **fail-closed**: ein gewählter http-Transport
ohne URL wirft, statt still auf Datei zurückzufallen.

Hinweis v1: Dieses Modul ist **additiv**. ``handoff_poll`` bleibt vorerst unberührt
(die Datei-Welt mit ihrer Stranded-Claim-/Requeue-Recovery ist erprobt). Sobald die
DCO-Endpunkte stehen, kann der Poller den Treiber über ``get_source()`` beziehen.
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

import bridge_common as bc


# --- Gemeinsamer Vertrag -----------------------------------------------------

@dataclass
class WorkItem:
    """Ein geclaimter Auftrag, transport-unabhängig.

    job_id     -- stabile ID (Datei: task_id; HTTP: jobs.job_id)
    input_text -- Roh-Payload/Seed-Text, den der Worker ausführt
    raw        -- transport-spezifischer Kontext (Datei: claimed_path/fm/body/lane)
    """
    job_id: str
    input_text: str
    raw: dict = field(default_factory=dict)


class Source:
    """Abstrakte Job-Quelle. claim_next() holt+claimt atomar, publish_result()
    meldet das Ergebnis zurück. Implementierungen MÜSSEN race-frei claimen."""

    def claim_next(self) -> WorkItem | None:                      # pragma: no cover
        raise NotImplementedError

    def publish_result(self, item: WorkItem, rc: int,
                        result_payload: dict | None = None,
                        result_status: str | None = None) -> None:  # pragma: no cover
        raise NotImplementedError


# --- Datei/Lane-Transport (heutiges Verhalten, gekapselt) --------------------

class FileSource(Source):
    """Wickelt die bestehende Lane/Datei-Welt in den Source-Vertrag.

    claim_next() scannt die receive-lanes des aktuellen Endpoints nach einer
    offenen ``task-*.md``, claimt sie über das erprobte ``bc.claim_task``
    (atomares ``os.rename`` + Sibling-Surrender) und gibt ein WorkItem zurück.
    publish_result() schreibt ein ``result-<id>.md`` in die Inbox derselben Lane.

    Die aufwändige Stranded-Claim-/Requeue-Recovery bleibt bewusst bei
    ``handoff_poll`` — diese Klasse deckt den Normalpfad (claim → result) ab und
    ändert NICHT das bestehende Poller-Verhalten.
    """

    def claim_next(self) -> WorkItem | None:
        bc.ensure_dirs()
        for lane in bc.receive_lanes():
            outbox = bc.lane_outbox(lane)
            if not outbox.exists():
                continue
            for task_path in sorted(outbox.glob("task-*.md")):
                if ".claimed-" in task_path.name:
                    continue
                claimed = bc.claim_task(task_path, bc.DEVICE)
                if claimed is None:
                    continue
                fm, body = bc.parse_frontmatter(bc.read_text_utf8(claimed))
                task_id = fm.get("task_id", bc._task_id_from_name(claimed.name))
                return WorkItem(
                    job_id=task_id,
                    input_text=body,
                    raw={"claimed_path": claimed, "fm": fm, "body": body,
                         "lane": lane},
                )
        return None

    def publish_result(self, item: WorkItem, rc: int,
                       result_payload: dict | None = None,
                       result_status: str | None = None) -> None:
        lane = item.raw.get("lane", bc.receive_lanes()[0])
        inbox = bc.lane_inbox(lane)
        inbox.mkdir(parents=True, exist_ok=True)
        payload = result_payload or {}
        summary = payload.get("summary", "")
        fm = {
            "task_id": item.job_id,
            "status": result_status or ("done" if rc == 0 else "error"),
            "rc": str(rc),
        }
        body = summary if summary else json.dumps(payload, ensure_ascii=False)
        result_path = inbox / f"result-{item.job_id}.md"
        bc.write_text_atomic(result_path, bc.build_document(fm, body))


# --- HTTP-Transport (DCO-Job-Pull) ------------------------------------------

# Cloudflare blockt den stdlib-Default-User-Agent ("Python-urllib/X") an einem
# Tunnel-geschützten Host mit 403 "error code: 1010". Ein expliziter,
# browser-ähnlicher UA kommt durch. (Live-Bug 2026-06-04, B-Worker über den
# bot.dynamic-dome.com-Tunnel.)
_USER_AGENT = "dual-bridge-worker/1.0 (+https://github.com/dynamic-dome/dual-bridge)"


def _safe_json(raw: bytes | None) -> dict | None:
    """Parse einen Response-Body als JSON, aber NIE crashen. Fehlerstatus liefern
    oft text/plain oder HTML (z.B. Cloudflare "error code: 1010") — dann None."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return None


def _urllib_client(method: str, url: str, json_body: dict | None,
                   headers: dict | None) -> tuple[int, dict | None]:
    """Default-HTTP-Client auf stdlib-Basis (keine Fremd-Deps). Wird in Tests
    durch einen Fake ersetzt — hier läuft also nie echtes Netz im Testlauf.

    Robust gegen nicht-JSON-Antworten: ein 403/404/5xx (oder ein durch eine
    Reverse-Proxy/Cloudflare ersetzter Body) wird als (status, None) gemeldet,
    nicht als Crash. Setzt einen expliziten User-Agent gegen Cloudflare-1010."""
    data = None
    hdrs = dict(headers or {})
    hdrs.setdefault("User-Agent", _USER_AGENT)
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.getcode(), _safe_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _safe_json(exc.read())


class HttpSource(Source):
    """DCO-Job-Pull über HTTP.

    claim_next()    -> GET  {base}/jobs/next?worker_type=<wt>   (204=leer, 200=Job)
    publish_result()-> POST {base}/jobs/<id>/result            {rc, payload, status}

    Der Claim selbst (queued→running) passiert serverseitig im DCO über dessen
    atomares ``transition_status`` — der Client sieht nur das Ergebnis. Der
    HTTP-Client ist injizierbar (``client``), damit Tests ohne Netz laufen; der
    Default nutzt stdlib ``urllib``.
    """

    def __init__(self, base_url: str, token: str | None = None,
                 worker_type: str = "dual-bridge",
                 client: Callable[..., tuple[int, dict | None]] | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.worker_type = worker_type
        self._client = client

    def _auth_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(self, method: str, path: str,
                 json_body: dict | None = None) -> tuple[int, dict | None]:
        headers = self._auth_headers()
        if self._client is not None:
            # Injizierter Fake bekommt den PFAD (für stabile Assertions).
            return self._client(method, path, json_body, headers)
        return _urllib_client(method, self.base_url + path, json_body, headers)

    def claim_next(self) -> WorkItem | None:
        path = f"/jobs/next?worker_type={self.worker_type}"
        status, body = self._request("GET", path)
        if status == 204 or not body:
            return None
        if status != 200:                                         # pragma: no cover
            return None
        return WorkItem(
            job_id=body["job_id"],
            input_text=body.get("input_text", ""),
            raw=body,
        )

    def publish_result(self, item: WorkItem, rc: int,
                       result_payload: dict | None = None,
                       result_status: str | None = None) -> None:
        path = f"/jobs/{item.job_id}/result"
        self._request("POST", path, {
            "rc": rc,
            "result_payload": result_payload or {},
            "result_status": result_status,
        })


# --- Treiberwahl -------------------------------------------------------------

def get_source() -> Source:
    """Wähle den Transport per ``DUAL_BRIDGE_TRANSPORT`` (Default 'file').

    fail-closed: ``http`` ohne ``DCO_BRIDGE_URL`` wirft; ein unbekannter Wert
    wirft ebenfalls (kein stiller Default)."""
    transport = os.environ.get("DUAL_BRIDGE_TRANSPORT", "file").strip().lower()
    if transport == "file":
        return FileSource()
    if transport == "http":
        url = os.environ.get("DCO_BRIDGE_URL", "").strip()
        if not url:
            raise ValueError(
                "DUAL_BRIDGE_TRANSPORT=http erfordert DCO_BRIDGE_URL "
                "(fail-closed: kein stiller Fallback auf Datei)."
            )
        return HttpSource(
            base_url=url,
            token=os.environ.get("DCO_BRIDGE_TOKEN") or None,
            worker_type=os.environ.get("DUAL_BRIDGE_WORKER_TYPE", "dual-bridge"),
        )
    raise ValueError(
        f"Unbekannter DUAL_BRIDGE_TRANSPORT={transport!r}. Erlaubt: file | http."
    )
