## Ziel
Ergänze in `scripts/bridge_notify.py` einen kompakten Docstring-Abschnitt, der die CLI-Exit-Codes des Notifiers (0/2/3) tabellarisch dokumentiert, damit ein Scheduler-Autor die Trigger-Auswertung ohne Quellcode-Studium versteht.

## Done-Kriterien
- [ ] der Modul-Docstring (oder der `main()`-Docstring) in `scripts/bridge_notify.py` listet explizit alle drei Exit-Codes mit Bedeutung: 0=ok/nichts-neues, 2=nicht konfiguriert, 3=mindestens ein Versandfehler
- [ ] die dokumentierten Codes stimmen exakt mit dem `return`-Verhalten von `main()` überein (verifiziert am Code, kein Widerspruch)
- [ ] kein bestehender Test bricht; `python -m pytest scripts/test_bridge_notify.py` bleibt grün
- [ ] die Änderung ist rein additiv (nur Doku/Docstring, keine Verhaltensänderung der Funktionen)
