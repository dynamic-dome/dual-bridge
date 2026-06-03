# HANDOFF an Claude auf Laptop B — Eigener Cloudflare-Tunnel für die Staging-DCO

*Von: Claude Code auf Laptop A · 2026-06-03 · Für: Claude Code auf Laptop B*
*Owner-Entscheidung: B bekommt einen EIGENEN Tunnel (Dauerlösung), nicht Tunnel-Teilen.*

---

## 1. Ziel (ein Satz)

Auf **Laptop B** einen **eigenen, benannten Cloudflare-Tunnel** mit **eigener Subdomain
`bot-staging.dynamic-dome.com`** aufsetzen, der auf die lokale **Staging-DCO (Port 8001)**
zeigt, und den **zweiten Telegram-Bot** per Webhook darauf umbiegen — sodass B und A
**dauerhaft konfliktfrei** koexistieren.

## 2. Warum (der Konflikt, den wir lösen)

- **Telegram stellt per Webhook zu** (Push, nicht Polling) → jede DCO-Instanz mit Telegram
  braucht einen **öffentlich erreichbaren HTTPS-Eingang**. Lokaler Laptop hat keine
  öffentliche IP → Cloudflare-Tunnel ist die Tür.
  Quelle: `dynamic_central_orchestrator/docs/ARCHITECTURE.md:5–34`.
- **Es gibt bisher nur EINEN Tunnel**: `dynamic-claude`
  (UUID `d41a7948-a06f-440c-96bf-b661824ef363`) → Hostname **`bot.dynamic-dome.com`** →
  `localhost:8000`. Quelle: `~/.cloudflared/config.yml` + `ARCHITECTURE.md:130–138`.
- **Kollision (empirisch bestätigt auf A):** `cloudflared tunnel list` zeigte für
  `dynamic-claude` **4 Connections (2xfra08,1xfra17,1xfra18)** = ZWEI Instanzen desselben
  Tunnels liefen gleichzeitig (A + B). Cloudflare load-balanced dann eine Telegram-Nachricht
  **mal auf A, mal auf B** — nicht-deterministisch. Genau das „in die Quere kommen": beide
  hatten denselben Namen + dieselbe URL.
- **Telegram erlaubt pro Bot-Token nur EINEN aktiven Webhook.** Deshalb braucht B sowohl
  einen **eigenen Tunnel/URL** ALS AUCH den **zweiten Bot-Token** (existiert laut Owner schon).

> Wichtig: **A nicht anfassen.** A behält `dynamic-claude` / `bot.dynamic-dome.com` / Port 8000.
> Alles hier ist additiv auf B.

## 3. Voraussetzungen prüfen (zuerst!)

```powershell
cloudflared --version                 # vorhanden?
cloudflared tunnel list               # zeigt es schon dynamic-claude-b? dann NICHT neu anlegen
Test-Path C:\Users\domes\.cloudflared\cert.pem   # Account-Login vorhanden?
```

- **`cert.pem` fehlt** → einmalig `cloudflared tunnel login` (öffnet Browser, Zone
  `dynamic-dome.com` autorisieren). Ohne `cert.pem` schlagen `create`/`route dns` fehl.
- Die Zone `dynamic-dome.com` liegt im selben Cloudflare-Account wie A — die DNS-Route
  ist also anlegbar.

## 4. Schritte (auf B ausführen)

```powershell
# (a) Eigenen benannten Tunnel anlegen — eigene UUID + eigene creds-json
cloudflared tunnel create dynamic-claude-b
#   → merkt sich die neue UUID; schreibt C:\Users\domes\.cloudflared\<NEUE-UUID>.json

# (b) DNS-Route für die eigene Subdomain auf diesen Tunnel zeigen lassen
cloudflared tunnel route dns dynamic-claude-b bot-staging.dynamic-dome.com

# (c) EIGENE Tunnel-Config schreiben — NICHT die bestehende config.yml überschreiben!
#     Lege eine separate Datei an, z.B. config-b.yml, und referenziere sie beim run mit --config.
```

**Inhalt von `C:\Users\domes\.cloudflared\config-b.yml`** (UUID aus Schritt (a) einsetzen):

```yaml
tunnel: <NEUE-UUID-AUS-SCHRITT-A>
credentials-file: C:\Users\domes\.cloudflared\<NEUE-UUID-AUS-SCHRITT-A>.json

ingress:
  - hostname: bot-staging.dynamic-dome.com
    service: http://localhost:8001
  - service: http_status:404
```

> ⚠️ Wenn auf B schon eine `config.yml` mit `dynamic-claude`/Port 8000 liegt (von der alten
> Tunnel-Teilung), lass sie liegen, aber **starte sie nicht** — sonst entsteht die Kollision
> erneut. B fährt ausschließlich `config-b.yml`.

```powershell
# (d) Staging-DCO auf 8001 starten (falls noch nicht läuft) — bestehendes Skript:
powershell -ExecutionPolicy Bypass -File C:\Users\domes\AI\dual-bridge\staging\start_staging_dco.ps1
#   (braucht ausgefüllte .env.staging mit dem 2. Bot-Token; siehe PICKUP-staging.md)

# (e) Eigenen Tunnel laufen lassen (eigene Config!)
cloudflared tunnel run --config C:\Users\domes\.cloudflared\config-b.yml dynamic-claude-b

# (f) Webhook des ZWEITEN Bots auf die neue URL biegen.
#     setup_webhook.py liest den Token aus der env (TELEGRAM_TOKEN = 2. Bot).
#     Es liest die env über config.py/.env — also im Staging-env-Kontext ausführen,
#     damit der 2. Token greift, NICHT der Prod-Token.
cd C:\Users\domes\dynamic_central_orchestrator
.\.venv\Scripts\python.exe setup_webhook.py
#   URL-Prompt beantworten mit:  https://bot-staging.dynamic-dome.com
```

> Achtung beim Webhook (f): `setup_webhook.py` importiert `TELEGRAM_API` aus `config.py`,
> das aus dem `TELEGRAM_TOKEN` der env gebaut wird. Stelle sicher, dass beim Aufruf der
> **Staging-Token** in der env steht (z.B. denselben env-Lade-Mechanismus nutzen wie
> `start_staging_dco.ps1`, der `.env.staging` als echte Prozess-env-Vars setzt), sonst
> verbiegst du versehentlich den **Prod**-Webhook von A. Im Zweifel: vor und nach (f)
> `getWebhookInfo` für BEIDE Tokens prüfen.

## 5. Done-Kriterien (verifizierbar, nicht „läuft schon")

1. `cloudflared tunnel list` zeigt **zwei** Tunnel: `dynamic-claude` UND `dynamic-claude-b`,
   und `dynamic-claude-b` hat **eigene Connections**.
2. `cloudflared tunnel list` zeigt für **`dynamic-claude` wieder nur die normalen ~2
   Connections** (= B benutzt ihn nicht mehr). Das ist der Beweis, dass die Kollision weg ist.
3. `https://bot-staging.dynamic-dome.com/` ist von außen erreichbar (HTTP-Antwort von der
   Staging-FastAPI, nicht 404 vom Tunnel-Fallback).
4. `getWebhookInfo` für den **2. Bot-Token** zeigt `url: https://bot-staging.dynamic-dome.com/webhook`.
5. `getWebhookInfo` für den **Prod-Bot-Token (A)** zeigt **unverändert** `bot.dynamic-dome.com`
   — A wurde NICHT verbogen.
6. Eine Testnachricht an den **2. Bot** landet bei der **Staging-DCO auf 8001** (nicht bei A).

## 6. Constraints / Stolpersteine

- **A niemals anfassen:** kein Eingriff in `config.yml`, `dynamic-claude`, Port 8000,
  Prod-`.env`, Prod-Webhook. Alles additiv.
- **Datenisolation der Staging-DCO** ist bereits gelöst (eigener `data_staging/`, eigener
  `DCO_AGENT_RUN_ROOT`) — siehe `start_staging_dco.ps1`. Nicht erneut bauen.
- **`ANTHROPIC_API_KEY` NICHT in die Staging-env** (Memory: DCO brain.py API-Key-Leak →
  API-Billing statt Abo). `.env.staging.template` warnt davor (Zeile 50–53).
- **Kein Secret committen / ins Sharepoint** (2. Bot-Token, WEBHOOK_SECRET, ADMIN_PIN).
- Falls `cloudflared` veraltet ist (A meldete 2026.5.1 < 2026.5.2): Update optional, nicht
  blockierend.
- Rückmeldung an A bitte als Bridge-Result / Handoff `from-laptop-b-to-claude-code` mit den
  6 Done-Kriterien als Belege (echte Befehlsausgaben, nicht „erledigt").

## 7. Referenz-Fundstellen (alle auf A verifiziert)

- `dynamic_central_orchestrator/docs/ARCHITECTURE.md:5–34` (Webhook-Kette),
  `:130–138` (Tunnel-Daten), `:117–128` (Deployment-Sequenz).
- `~/.cloudflared/config.yml` (A's Tunnel = dynamic-claude → bot.dynamic-dome.com → :8000).
- `dynamic_central_orchestrator/setup_webhook.py` (setWebhook-Mechanik, URL-Prompt).
- `AI/dual-bridge/staging/.env.staging.template` + `start_staging_dco.ps1` +
  `PICKUP-staging.md` (Staging-DCO-Isolation, Port 8001, 2. Bot-Token).
