## Ziel
Erweitere den Modul-Docstring in `scripts/bridge_overnight.py` um eine kompakte Tabelle, die jedes CLI-Flag des Overnight-Schedulers kurz erklärt. Aktuell listet der Docstring die Flags nur in der Aufruf-Zeile auf, ohne ihre Bedeutung. Die bereits vorhandene Exit-Mapping-Zeile bleibt unverändert.

## Done-Kriterien
- [ ] der Modul-Docstring in `scripts/bridge_overnight.py` erklärt jedes der sechs CLI-Flags mit je 1 Zeile: `--queue <dir>` (Seed-Verzeichnis), `--repo <url>` (Ziel-Repo), `--max-rounds <n>` (Default 4), `--round-timeout <s>` (Default 600), `--dry-run` (nur listen, nichts starten/senden), `--no-notify` (kein Telegram-Digest)
- [ ] die dokumentierten Flags + Defaults stimmen exakt mit der `argparse`-Definition (`p.add_argument(...)`) überein (verifiziert am Code, kein Widerspruch)
- [ ] die bestehende Zeile `Exit-Mapping (loop_driver-Contract): 0=accepted, 3=escalated, 2/1=error.` bleibt unverändert erhalten
- [ ] kein bestehender Test bricht; `python -m pytest scripts/test_bridge_overnight.py` bleibt grün
- [ ] die Änderung ist rein additiv (nur Docstring, keine Verhaltensänderung der Funktionen)
