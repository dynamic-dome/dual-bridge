## Ziel
Ergänze in `scripts/bridge_status.py` einen kompakten Docstring-Abschnitt, der die CLI-Flags des read-only Status-Dashboards tabellarisch dokumentiert (`--format`, `--lane`, `--watch`, `--interval`), damit ein Aufrufer die Optionen ohne Quellcode-Studium versteht.

## Done-Kriterien
- [ ] der Modul-Docstring in `scripts/bridge_status.py` listet alle vier CLI-Flags mit je 1 Zeile Bedeutung: `--format {text,json}` (Ausgabeformat, Default text), `--lane <name>` (nur diese Lane, Default alle), `--watch` (periodisch neu rendern, read-only), `--interval <s>` (Sekunden zwischen Watch-Refreshes, Default 3)
- [ ] die dokumentierten Flags + Defaults stimmen exakt mit der `argparse`-Definition in `_parse_args()` überein (verifiziert am Code, kein Widerspruch)
- [ ] der Docstring stellt klar, dass das Tool read-only ist und immer Exit-Code 0 liefert (keine erfundenen Fehler-Codes)
- [ ] kein bestehender Test bricht; `python -m pytest scripts/test_bridge_status.py` bleibt grün
- [ ] die Änderung ist rein additiv (nur Doku/Docstring, keine Verhaltensänderung der Funktionen)
