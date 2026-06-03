# RESULT an Laptop A — Eigener Cloudflare-Tunnel auf Laptop B steht

*Von: Claude Code auf Laptop B · 2026-06-03 · Antwort auf: HANDOFF-tunnel-b-eigener-tunnel.md*
*Status: **ERLEDIGT** — alle 6 Done-Kriterien verifiziert (echte Befehlsausgaben unten).*

---

## Zusammenfassung

Laptop B hat jetzt einen **eigenen, benannten Tunnel** `dynamic-claude-b`
(UUID `111fb9f2-eee5-4b58-a707-bf1339af73cc`) mit eigener Subdomain
**`bot-staging.dynamic-dome.com`** → **localhost:8001** (Staging-DCO).
**A wurde NICHT angefasst.** Die Load-Balancing-Kollision ist beseitigt.

Zusätzlich (vom Owner gewünscht, war nicht im Handoff): Der **alte geteilte
Tunnel-Dienst** (`Cloudflared`, der bisher `dynamic-claude`/`bot.dynamic-dome.com`
fuhr) wurde auf **StartMode=Manual** gesetzt und gestoppt — er startet auf B nicht
mehr automatisch beim Boot. Das war die eigentliche Ursache der „Ausfälle, wenn
dieser PC an ist".

## Done-Kriterien (mit Belegen)

**1+2. Zwei Tunnel, getrennte Connections** ✅
```
ID                                   NAME             CONNECTIONS
d41a7948-...                         dynamic-claude   2xfra08, 1xfra17, 1xfra18   (A, unberührt)
111fb9f2-...                         dynamic-claude-b 2xfra08, 2xfra18            (B, eigene)
```

**3. `https://bot-staging.dynamic-dome.com/` von außen erreichbar** ✅
```
GET https://bot-staging.dynamic-dome.com/health -> HTTP 200 {"status":"ok"}
```

**4. Webhook des 2. Bots zeigt auf bot-staging** ✅
```
Bot 8882052060 getWebhookInfo:
  url: https://bot-staging.dynamic-dome.com/webhook
```

**5. Prod-Webhook (A) UNVERÄNDERT** ✅
```
Bot 8725974981 getWebhookInfo:
  url: https://bot.dynamic-dome.com/webhook   (vor + nach identisch)
```

**6. Webhook-Request landet bei Staging-DCO auf 8001** ✅
```
POST /webhook MIT korrektem Secret  -> HTTP 200
POST /webhook OHNE Secret           -> HTTP 403 (Auth greift)
Staging-DCO-Log: "Unauthorized chat_id: 1" + "Webhook request with invalid secret token"
(= Requests erreichen die Staging-Instanz und durchlaufen deren Security-Layer)
```

## Was angelegt wurde (auf B)

- Tunnel `dynamic-claude-b` + creds-json `~/.cloudflared/111fb9f2-...json`
- DNS-CNAME `bot-staging.dynamic-dome.com` → dynamic-claude-b (per UUID gesetzt,
  s. Stolperstein unten)
- `~/.cloudflared/config-b.yml` (Port 8001) — **A's config.yml unangetastet**
- Webhook + Mini-App-Menü-Button für den 2. Bot (8882052060)
- Steuer-Schalter: `tunnel-b-on.bat` / `tunnel-b-off.bat` / `tunnel-b-status.bat`
  (+ `tunnel-b-control.ps1`) im staging-Ordner

## Stolpersteine (für die Akten)

1. **`dream-team`-Repo fehlte auf B** → Staging-DCO crashte beim Import
   (`ModuleNotFoundError: No module named 'dream_team'`, via
   `mcp_servers/duett/api.py`). Ursache: `_dream_team_path.py` + editable-install
   erwarten `C:\Users\domes\Desktop\Claude-Projekte\dream-team`, dieser Pfad
   existiert auf B nicht (System-B-Migration: realer Pfad ist
   `Desktop\Development\Claude\Claude-Projekte\`). **Fix: Directory-Junction**
   `Desktop\Claude-Projekte` → `Desktop\Development\Claude\Claude-Projekte`
   (behebt auch alle anderen Projekte, die auf den alten Pfad zeigen; reversibel).

2. **`cloudflared tunnel route dns <NAME>`** routete fälschlich auf A's Tunnel,
   weil cloudflared den Namen gegen die vorhandene `config.yml` (= A) auflöste.
   **Fix: per UUID + `--overwrite-dns`** geroutet.

3. **`cloudflared --config` MUSS vor `tunnel run`** stehen (globales Flag), sonst
   gibt cloudflared nur die Hilfe aus. In den .bat-Schaltern korrekt.

## Offen / nicht getan

- cloudflared auf B ist `2025.8.1` (A meldete dasselbe) — Update auf `2026.5.2`
  optional, nicht blockierend.
- Kein Autostart für Tunnel-B eingerichtet (bewusst — Owner will manuell steuern,
  via .bat). Falls später Autostart gewünscht: eigener Dienst NUR mit config-b.yml.
