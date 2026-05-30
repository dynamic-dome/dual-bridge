# PICKUP — Staging-DCO auf B (Idee 4)

> Schnellanleitung. Voller Kontext: `01_HANDOFFS/2026-05-30-from-claude-code-A-to-laptop-b-staging-dco-idee4.md`.

## Was das ist
Zweite, isolierte DCO-Instanz neben Prod auf B. Trennung über eigenen Daten-Ordner,
eigenen Bot-Token, eigenen Port 8001. **Kein DCO-Code wird geändert.**

## Dateien hier
- `.env.staging.template` — alle Pflicht-Secrets mit Platzhaltern
- `start_staging_dco.ps1` — Start-Skript (direkter uvicorn 8001, an Tray/Mutex vorbei)

## In 4 Schritten
1. **`git pull`** auf B (DCO + Wiki — B ist ~1 Woche alt).
2. Diese 2 Dateien nach `<B>\AI\dual-bridge\staging\` kopieren.
3. `.env.staging.template` → `.env.staging`, Platzhalter füllen:
   - `TELEGRAM_TOKEN` = 2. BotFather-Token (Owner legt an)
   - `WEBHOOK_SECRET`, `ADMIN_PIN` = **eigene** Staging-Werte (nicht Prod kopieren):
     `python -c "import secrets; print(secrets.token_urlsafe(24))"`
4. `powershell -ExecutionPolicy Bypass -File start_staging_dco.ps1`

## Drei Fallen, die das Skript für dich abfängt
- Port 8000 ist Prod (hardcoded in tray.pyw) → Staging nimmt 8001.
- Tray ist single-instance (Mutex) → Start läuft an der Tray-App vorbei.
- `load_dotenv()` liest nur `.env` (=Prod) → Skript setzt Staging-Werte als echte env-Vars.

## Verifikation (nicht dem Start-Log blind trauen)
- `data_staging/` neu + separat von `data/`
- Prod auf 8000 läuft unberührt weiter
- Staging-`jobs.db` leer/frisch, Prod-`data/jobs.db` unangetastet

## Rückmeldung
Als Bridge-Result oder Handoff `from-laptop-b-to-claude-code`: läuft 8001? isoliert? Fehler?
