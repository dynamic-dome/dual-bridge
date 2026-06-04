# Beispiel-Seeds (Mechanik-Test, NICHT in der aktiven Queue)

Diese Seeds sind **Wegwerf-Übungen**, um den Overnight-Scheduler und die
Cross-Device-Mechanik zu testen — kleine, in einer Iteration baubare Aufgaben.

Weil sie in einem **Unterordner** liegen, werden sie von `bridge_overnight.py`
**nicht** automatisch aufgegriffen (der Scheduler zählt nur die oberste Ebene von
`docs/overnight/`). Die echte aktive Queue liegt eine Ebene höher.

## Verwenden

Zum Ausprobieren einen Seed temporär nach oben kopieren, z. B.:

```bash
cp docs/overnight/_examples/01-greet-util.md docs/overnight/90-greet-util.md
python scripts/bridge_overnight.py --dry-run --repo <REPO>
# danach wieder entfernen oder auf .skip umbenennen
```

Oder den Scheduler gezielt auf diesen Ordner zeigen lassen:

```bash
python scripts/bridge_overnight.py --dry-run --queue docs/overnight/_examples --repo <REPO>
```

Siehe auch das vollständige Runbook:
`docs/live-proofs/RUNBOOK-cross-device-test-chains.md` (Kette 3).
