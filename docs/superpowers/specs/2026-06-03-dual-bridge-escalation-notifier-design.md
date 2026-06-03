# Dual-Bridge — Eskalations-Notifier (Telegram, lokal getriggert)

*Erstellt: 2026-06-03 · Repo: `dynamic-dome/dual-bridge` · baut auf `bridge_status.py` + `ESCALATION-<id>.md` auf*

## Kontext & Motivation

Der Goal-Loop kann eskalieren (`loop_driver.write_escalation` → `state/ESCALATION-<id>.md`),
und das Status-Dashboard (`bridge_status.py`) *zeigt* offene Eskalationen prominent an.
Aber: **niemand wird aktiv benachrichtigt.** Wenn nachts ein Loop eskaliert, bleibt die
`ESCALATION-<id>.md` liegen, bis jemand zufällig das Dashboard öffnet. Der Owner ist der
einzige, der die offene Frage beantworten kann — er muss es nur erfahren.

Dieser Baustein schließt genau diese Lücke: Er **pusht neue Eskalationen aktiv per Telegram**
an den Owner. Das Dashboard ist die *Pull*-Sicht (ich schaue rein); der Notifier ist die
*Push*-Kante (es meldet sich bei mir).

### Leitprinzip (die Invariante)

Der Notifier ist eine **Push-Kante über den Eskalations-Artefakten — er ändert den
Loop-/Bridge-Zustand NICHT.** Er liest `ESCALATION-*.md`, schickt eine Nachricht und merkt
sich ausschließlich in **seinem eigenen** Sidecar-State, was schon gemeldet wurde. Er claimt
keine Tasks, verschiebt keine Eskalationen, schreibt nichts in `state/ESCALATION-*` oder die
Lanes. Damit bleibt er — wie das Dashboard — gefahrlos beliebig oft ausführbar.

### Self-contained, aber DCO-ready

Der Notifier funktioniert **allein** (lokaler Trigger via Windows Scheduled Task, analog zum
bestehenden `register_watchdog.ps1`). Die Versand-Logik lebt aber in einer reinen Funktion
`notify_new_escalations()`, die von *irgendeinem* Aufrufer angestoßen werden kann — heute der
OS-Task, später optional DCO. Umstieg auf DCO ändert nur den Aufrufer, **keine Zeile** im
Notifier.

## Ground-Truth: was bereits existiert (verifiziert am Code, nichts neu)

- **`state/ESCALATION-<loop_id>.md`** — durable Eskalations-Artefakt. Frontmatter-Felder
  (aus `loop_driver.write_escalation`): `loop_id`, `trigger`, `round`, `branch`, `commit`,
  `exit_reason`, `created`. Body-Abschnitte: `## Ziel (aus dem Seed)`,
  `## Done-Kriterien`, `## Eskalations-Grund`, `## Offene Frage an den Owner`,
  `## Zwischenstand`.
- **`bridge_status.scan_escalations(state_dir)`** — liest offene `ESCALATION-*.md` (ignoriert
  `_processed/`), liefert `EscalationInfo`-Objekte (`loop_id`, `trigger`, `round`, `branch`,
  `commit`, `created`). Der Notifier nutzt diese Funktion als Quelle — keine Doppel-Parsing-Logik.
- **`bridge_common`** — `parse_frontmatter`, `read_text_utf8`, `write_text_utf8`, `now_iso`,
  `safe_subprocess_env`, `default_lock_path`, `_pid_alive`, `STATE_DIR`-Muster.
- **`register_watchdog.ps1`** — erprobtes Muster für einen Windows Scheduled Task, der ein
  Python-Skript periodisch startet. Der Notifier-Trigger wird analog gebaut.

## Architektur — additiv, kein Umbau

Ein neues, eigenständiges Skript **`scripts/bridge_notify.py`** plus ein optionales
**`scripts/register_notify.ps1`** für den lokalen Trigger. Kein bestehender Code wird
verändert; `bridge_status.scan_escalations` wird nur *gelesen*.

### Komponente 1 — Eskalations-Quelle (wiederverwendet)

`bridge_notify` ruft `bridge_status.scan_escalations(STATE_DIR)` auf und bekommt die Liste der
aktuell offenen Eskalationen. Keine eigene Verzeichnis-Logik — Single Source of Truth bleibt
das Dashboard-Modul.

### Komponente 2 — Dedup-State (Sidecar, eigener Besitz)

Damit dieselbe Eskalation **nicht bei jedem Trigger erneut** gepingt wird, führt der Notifier
eine eigene Merk-Datei: `state/_notify/sent.json` (read-modify-write, atomar via
`write_text_atomic`).

- Schlüssel = `loop_id` (eindeutig pro Eskalation). Optional Wert = `{created, notified_at}`.
- **Neu** = eine offene Eskalation, deren `loop_id` NICHT in `sent.json` steht.
- Der Notifier schreibt **ausschließlich** in `state/_notify/` — niemals in `ESCALATION-*.md`
  oder die Lanes (Invariante).
- Wird eine Eskalation abgearbeitet (verschwindet aus `scan_escalations`), bleibt ihr Eintrag
  in `sent.json` stehen (harmlos) ODER wird beim nächsten Lauf bereinigt (Reconcile, siehe
  unten). Keine Re-Notification, wenn ein gleichnamiger Loop nie wieder auftaucht.

### Komponente 3 — Telegram-Transport (allowlist-env, fail-safe)

- **Konfiguration über Env** (kein Secret im Repo, keine Hardcodes): primär die
  bestehenden DCO-Namen `TELEGRAM_TOKEN` (Bot-Token) und `TELEGRAM_CHAT_ID` (Chat-ID),
  damit Notifier und DCO sich **eine** Credential-Quelle teilen. Optionaler Override
  über `DUAL_BRIDGE_TG_TOKEN` / `DUAL_BRIDGE_TG_CHAT` (erste gesetzte Variable gewinnt:
  DUAL_BRIDGE_TG_* > TELEGRAM_*).
- **Versand** via `https://api.telegram.org/bot<token>/sendMessage` (POST, `chat_id` + `text`,
  `parse_mode=Markdown`). Reine `urllib`-Standardbibliothek — keine neue Abhängigkeit.
- **Fail-safe:** Fehlt Token/Chat → der Notifier macht **keinen** Versand, schreibt eine klare
  Meldung auf stdout und endet mit rc≠0 (Trigger sieht „nicht konfiguriert"), **markiert aber
  nichts als gesendet** (sonst gingen Eskalationen still verloren).
- **Netzwerkfehler** (Telegram nicht erreichbar, HTTP-Fehler) → Eskalation wird **NICHT** als
  gesendet markiert, Fehler wird geloggt, nächster Trigger versucht es erneut (at-least-once,
  nie still verloren). Mehrere Eskalationen werden einzeln verschickt; ein Fehler bei einer
  blockiert die anderen nicht.
- **Injection-sicher:** Nachrichtentext wird aus den geparsten Frontmatter-Feldern gebaut;
  freie Body-Teile (z.B. die „offene Frage") werden gekürzt und Markdown-escaped, damit ein
  bösartiger Eskalations-Inhalt das Telegram-Markup nicht kapert.

### Komponente 4 — Nachrichten-Format

Eine knappe, mobil lesbare Nachricht pro neuer Eskalation:

```
🚨 dual-bridge Eskalation
Loop: <loop_id>
Trigger: <trigger>  (Runde <round>)
Branch: <branch> @ <commit>
Frage: <offene Frage an den Owner, gekürzt>
Seit: <created>
```

Renderfunktion `format_escalation_message(info, question)` → reiner String, unit-testbar ohne
Netzwerk.

### Komponente 5 — Optionaler Tages-Digest (Schalter, default aus)

Neben dem Eskalations-Alert kann der Notifier auf Wunsch eine **tägliche Status-Zusammenfassung**
schicken (z.B. „3 offen, 1 geclaimt, 0 Eskalationen, Poller läuft"), gespeist aus
`bridge_status.build_report().summary`. Standardmäßig **aus** (`--digest` aktiviert es). So
bleibt der Default ruhig: nur melden, wenn etwas Dringendes passiert.

### CLI (endpoint-relativ, identisch auf A und B)

```
python bridge_notify.py                 # neue Eskalationen pingen (Default)
python bridge_notify.py --dry-run       # nur anzeigen, was gesendet würde; NICHTS senden, NICHTS markieren
python bridge_notify.py --digest        # zusätzlich die Tages-Zusammenfassung senden
python bridge_notify.py --reconcile     # sent.json gegen aktuelle Eskalationen bereinigen (kein Versand)
```

- `--dry-run` ist der sichere Erst-Lauf: zeigt die Nachrichten, ohne Telegram zu berühren und
  ohne `sent.json` zu ändern (perfekt zum Testen der Konfiguration).
- Respektiert `DUAL_BRIDGE_STATE` (Test-Isolation, wie beim Dashboard) und
  `DUAL_BRIDGE_ENDPOINT`.
- Exit-Codes: `0` = ok (auch „nichts Neues"), `2` = nicht konfiguriert, `3` = Versandfehler
  (mind. eine Eskalation konnte nicht zugestellt werden — für den Trigger sichtbar).

### Lokaler Trigger — `register_notify.ps1`

Analog zu `register_watchdog.ps1`: registriert einen Windows Scheduled Task
`DualBridgeEscalationNotifier`, der `bridge_notify.py` periodisch startet (Default alle 10 min;
für den Digest optional ein zweiter Once-täglich-Task mit `--digest`). Der Notifier ist
idempotent (Dedup via `sent.json`), daher ist blindes periodisches Starten sicher — analog zum
Singleton-Lock-Schutz des Pollers. Aktivierung bewusst erst **nach** einem erfolgreichen
`--dry-run`.

## Testen

### Unit (`scripts/test_bridge_notify.py`; gegen tmp-State, KEIN echtes Telegram)

Der Telegram-Versand wird über einen injizierbaren Sender gemockt (z.B. `send_fn`-Parameter
oder monkeypatchbares `_post_telegram`), sodass kein Test je das Netz berührt.

1. **`test_new_escalation_triggers_send`** — eine offene `ESCALATION-*.md`, `sent.json` leer →
   genau ein Send-Call, danach steht der `loop_id` in `sent.json`.
2. **`test_already_sent_escalation_is_not_resent`** — derselbe `loop_id` ist in `sent.json` →
   kein Send-Call (Idempotenz).
3. **`test_multiple_new_escalations_each_sent_once`** — drei neue → drei Send-Calls, alle drei
   in `sent.json`.
4. **`test_send_failure_does_not_mark_sent`** — Sender wirft/HTTP-Fehler → `loop_id` landet
   NICHT in `sent.json`, rc=3; nächster Lauf versucht erneut (at-least-once).
5. **`test_partial_failure_isolates`** — drei neue, der mittlere Send schlägt fehl → die zwei
   erfolgreichen sind markiert, der fehlgeschlagene nicht; rc=3.
6. **`test_not_configured_returns_2_and_marks_nothing`** — kein Token/Chat → kein Send, rc=2,
   `sent.json` unverändert.
7. **`test_dry_run_sends_nothing_marks_nothing`** — `--dry-run` mit neuer Eskalation → kein
   Send-Call, `sent.json` unverändert, Ausgabe enthält die geplante Nachricht.
8. **`test_message_format_contains_key_fields`** — `format_escalation_message` enthält
   `loop_id`, `trigger`, `round`, die offene Frage.
9. **`test_message_escapes_markdown_injection`** — eine Eskalation mit `*`/`_`/`[` in der
   offenen Frage → der gebaute Text kann das Telegram-Markup nicht kapern (escaped/gekürzt).
10. **`test_reconcile_drops_stale_entries`** — `sent.json` enthält einen `loop_id`, der nicht
    mehr offen ist → `--reconcile` entfernt ihn, ohne zu senden.
11. **`test_notifier_is_read_only_on_escalations`** — Snapshot des `ESCALATION-*.md`-Baums vor
    und nach einem vollen Lauf identisch (Invariante: schreibt nur in `state/_notify/`).
12. **`test_digest_summarizes_without_escalation`** — `--digest`, keine Eskalation, aber offene
    Tasks → genau ein Send-Call mit der Zusammenfassung (open/claimed/…).

Dual-runnable wie der Rest der Suite (`pytest` + `__main__`-Block). Isolation über
`DUAL_BRIDGE_STATE` (tmp), wie bei den Dashboard-Tests. Volle Suite bleibt grün (158 → 170).

### Live-Smoke (separater Schritt, NICHT in der Unit-Suite — P007)

Mit echten `DUAL_BRIDGE_TG_TOKEN`/`_CHAT`: erst `--dry-run` (zeigt die Nachricht), dann ein
echter Lauf gegen eine Test-Eskalation → eine reale Telegram-Nachricht erscheint. Bewusst
außerhalb der automatischen Tests, weil er ein echtes Konto + Netz braucht.

## Erfolgskriterien

- [ ] `bridge_notify.py` schickt für jede **neue** offene Eskalation **genau eine** Telegram-Nachricht.
- [ ] Bereits gemeldete Eskalationen werden **nie** erneut gepingt (Dedup via `sent.json`).
- [ ] Ein Versandfehler markiert **nichts** als gesendet → keine still verlorene Eskalation (at-least-once).
- [ ] Fehlende Konfiguration → rc=2, kein Versand, kein State-Schreiben.
- [ ] `--dry-run` berührt weder Telegram noch `sent.json`.
- [ ] Der Notifier schreibt **ausschließlich** in `state/_notify/` — Snapshot-Test beweist
      Unversehrtheit der `ESCALATION-*.md` (Invariante).
- [ ] Markdown-Injection im Eskalations-Inhalt kann das Telegram-Markup nicht kapern.
- [ ] Versand-Logik liegt in `notify_new_escalations()` — Aufrufer (OS-Task heute, DCO später)
      austauschbar ohne Notifier-Änderung.
- [ ] 12 neue Tests grün; volle Suite ohne Regression.

## Bewusst draußen (YAGNI)

- **Kein** Reply-Handling über Telegram (Owner antwortet weiter im Loop/Reseed, nicht im Chat).
  Der Notifier ist eine reine Ausgangskante.
- **Kein** eigener Scheduler/Daemon im Python — der Trigger ist der OS-Task (bzw. später DCO).
  Der Notifier ist ein kurzlebiger Ein-Schuss-Prozess.
- **Kein** Multi-Channel (Pushover/E-Mail) — Telegram only, wie entschieden. Der Transport ist
  hinter einer Sendefunktion gekapselt, falls das je erweitert wird.
- **Keine** Eskalations-Mutation (z.B. Verschieben nach `_processed/` nach Versand) — das
  bleibt Sache dessen, der die Eskalation tatsächlich abarbeitet, nicht des Melders.

## Folge-Arbeit (nicht Teil dieser Spec)

- **Overnight-Scheduler** für den Goal-Loop selbst (autonomes Weiterfahren nachts) — eigener
  Baustein, baut auf demselben lokal-vs-DCO-Muster auf.
- **DCO-Integration** als alternativer Trigger (statt/zusätzlich zum OS-Task).
