## Ziel
Ergänze `HOW-TO-USE.md` um einen kompakten Doku-Index-Abschnitt, der auf alle vorhandenen `docs/*.md`-Dateien verlinkt, damit ein neuer Mitarbeiter die Zusatz-Dokumentation findet, ohne das `docs/`-Verzeichnis zu durchsuchen. Aktuell verlinkt `HOW-TO-USE.md` nur die README.

## Done-Kriterien
- [ ] `HOW-TO-USE.md` enthält einen neuen Abschnitt (z.B. `## Weitere Dokumentation`) mit Markdown-Links auf jede `.md`-Datei direkt in `docs/` — konkret: `docs/CHANGELOG.md`, `docs/latency-baseline.md`, `docs/state-layout.md`
- [ ] jeder verlinkte Pfad existiert tatsächlich im Repo (kein toter Link; relativ zum Repo-Root prüfbar)
- [ ] jeder Link hat einen kurzen (≤1 Satz) Hinweis, was die Datei enthält
- [ ] die Änderung ist rein additiv (nur ein neuer Abschnitt in `HOW-TO-USE.md`, keine bestehende Zeile entfernt oder umgeschrieben)
