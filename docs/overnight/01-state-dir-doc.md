## Ziel
Dokumentiere das `state/`-Verzeichnis-Layout der dual-bridge in einer neuen Datei `docs/state-layout.md`, damit ein neuer Mitarbeiter die Sidecar-Verzeichnisse (`_notify/`, `_overnight/`, `_errors/`, `work/`, Lanes) ohne Code-Lektüre versteht.

## Done-Kriterien
- [ ] eine neue Datei `docs/state-layout.md` existiert im Repo
- [ ] sie beschreibt jedes der folgenden Verzeichnisse mit je 1-2 Sätzen: `state/lane-A-to-B/`, `state/lane-B-to-A/`, `state/_errors/` (Quarantäne), `state/_notify/` (sent.json), `state/_overnight/runs/`, `state/work/<loop_id>/`
- [ ] sie macht klar, welche Komponente in welches Verzeichnis schreibt (Poller, loop_driver, bridge_notify, bridge_overnight) und welche nur lesen
- [ ] der Inhalt stimmt mit dem tatsächlichen Code überein (keine erfundenen Verzeichnisse); Pfadnamen sind verifizierbar in `bridge_status.py`/`bridge_notify.py`/`bridge_overnight.py` belegt
- [ ] die Datei ist aus `HOW-TO-USE.md` verlinkt
