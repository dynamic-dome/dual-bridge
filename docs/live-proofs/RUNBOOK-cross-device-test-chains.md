# Runbook: Cross-Device-Test-Ketten für dual-bridge

- **Datum:** 2026-06-04
- **Zweck:** Die dual-bridge mit kleinen, iterativ baubaren Päckchen über zwei echte
  Geräte testen — jedes Gerät baut ein Stück, reicht rüber, das andere baut an,
  reicht zurück. Prüft die **Continuity über Geräte- und Iterations-Grenzen**.
- **Gilt für:** echte Hardware (Laptop A = `claude@laptop-a`, Laptop B =
  `codex@laptop-b`) mit synchronisiertem Bridge-Root über Drive/Sharepoint.
  In der Sandbox nicht ausführbar (keine zwei Geräte, kein Drive).

> **Grundbegriffe**
> - **A** = `claude@laptop-a` (Default-Endpoint). Sendet auf Lane `A-to-B`, empfängt auf `B-to-A`.
> - **B** = `codex@laptop-b`. Sendet auf `B-to-A`, empfängt auf `A-to-B`.
> - Richtung ergibt sich allein aus `DUAL_BRIDGE_ENDPOINT` — derselbe Code auf beiden.
> - Jedes Päckchen = ein Task. Empfänger **claimt** ihn, ein Runner baut, das
>   **Result** geht in die Gegen-Lane zurück.

---

## Vorbereitung (auf BEIDEN Geräten, einmalig)

```bash
cd ~/AI/dual-bridge/scripts          # Pfad ggf. anpassen
# Wer bin ich?  (auf A weglassen = Default; auf B setzen)
#   Laptop A:  (nichts setzen, Default ist claude@laptop-a)
#   Laptop B:  setze die Identität:
export DUAL_BRIDGE_ENDPOINT="codex@laptop-b"     # NUR auf B
# Optional, falscher Drive-Pfad auf B:
# export DUAL_BRIDGE_ROOT="/pfad/zum/dual-bridge"
```

**Dauer-Poller auf dem EMPFÄNGER laufen lassen** (verarbeitet eingehende Tasks):
```bash
python handoff_poll.py --watch --interval 10
```
> Tipp: Lass auf **beiden** Geräten je einen `handoff_poll.py --watch` laufen, dann
> funktioniert jede Richtung sofort. Jeder pollt nur seine `receive_lanes` — ein
> Claim-Race ist strukturell ausgeschlossen.

---

## Kette 1 — increment-Smoke (deterministisch, kein LLM)

**Was sie beweist:** der reine Transport- und Claim-Mechanismus wandert sauber hin
und zurück, und der Zustand (eine Zahl) wächst über die Hops korrekt. Jede
Abweichung ist ein echter Bug, kein LLM-Rauschen. **Hier zuerst anfangen.**

Der `increment`-Runner nimmt die Payload als Zahl und gibt `+1` zurück.

**Hop 1 — A startet mit 0, erwartet 1 zurück:**
```bash
# auf A:
python handoff_write.py --adapter increment --kind echo "0"
python handoff_collect.py --watch          # wartet auf Result aus B-to-A
# Result-Payload muss "1" sein.
```

**Hop 2 — A reicht die 1 rüber, erwartet 2:**
```bash
# auf A:
python handoff_write.py --adapter increment --kind echo "1"
python handoff_collect.py --watch          # Result-Payload "2"
```

**Hop 3..n — beliebig fortsetzen** (`"2"` -> `3`, `"3"` -> `4`, …). Du siehst nach
jedem Hop im Result-Frontmatter `claimed_by: codex@laptop-b@<DEVICE>` und die um 1
erhöhte Payload. **Erfolg = jede Zahl kommt exakt +1 zurück, kein Hop verloren.**

> Negativtest (optional): `--adapter increment "nicht-eine-zahl"` muss als FEHLER
> zurückkommen (Result enthält `## FEHLER`), nicht als Erfolg.

---

## Kette 2 — codex Mini-Inkremente (echtes Cross-Device-Bauen)

**Was sie beweist:** ein echtes Code-Artefakt wächst Hop für Hop über beide Geräte;
jeder Hop ist ein eigener Branch `bridge/task-<id>`, den der Empfänger committet +
pusht. Continuity bedeutet hier: jeder Schritt baut nachweislich auf dem vorherigen auf.

> **Voraussetzung:** `codex` auf B verfügbar/eingeloggt; `--repo` zeigt auf dein
> Test-Repo. Verwende ein **Wegwerf-/Test-Repo** oder einen Test-Branch — die Kette
> erzeugt mehrere Branches.

Ersetze `<REPO>` durch deine Repo-URL (oder lokalen Pfad auf B).

**Hop 1 — A → B: Fundament legen**
```bash
# auf A:
python handoff_write.py --adapter codex --kind implement --repo <REPO> \
  "Lege chain_demo/chain.py an mit: def step1() -> list: return [1].  Mit Docstring.  Nur diese eine Funktion, keine weiteren Änderungen."
python handoff_collect.py --watch
# Ergebnis: Branch bridge/task-<id1> mit chain.py + step1().
```

**Hop 2 — B → A: darauf aufbauen**
> Wechsle die aktive Seite: lass A den Branch aus Hop 1 mergen/auschecken, dann
> sendet **B** den nächsten Auftrag an A (B ist Producer, A baut).
```bash
# auf B (DUAL_BRIDGE_ENDPOINT=codex@laptop-b):
python handoff_write.py --adapter codex --kind implement --repo <REPO> \
  "Erweitere chain_demo/chain.py um: def step2(xs: list) -> list: return xs + [2].  step2 baut auf der Ausgabe von step1 auf.  step1 unverändert lassen."
python handoff_collect.py --watch
```

**Hop 3 — A → B: nächstes Glied**
```bash
# auf A:
python handoff_write.py --adapter codex --kind implement --repo <REPO> \
  "Füge chain_demo/chain.py hinzu: def step3(xs: list) -> list: return xs + [3].  step1/step2 unverändert."
python handoff_collect.py --watch
```

**Hop 4 — B → A: verketten**
```bash
# auf B:
python handoff_write.py --adapter codex --kind implement --repo <REPO> \
  "Füge chain_demo/chain.py die Funktion run_chain() hinzu, die step1, step2, step3 in dieser Reihenfolge verkettet und [1, 2, 3] zurückgibt.  Mit Docstring."
python handoff_collect.py --watch
```

**Hop 5 — A → B: absichern**
```bash
# auf A:
python handoff_write.py --adapter codex --kind implement --repo <REPO> \
  "Füge chain_demo/test_chain.py hinzu mit einem Test, der run_chain() == [1, 2, 3] prüft.  Keine bestehende Funktion ändern."
python handoff_collect.py --watch
```

**Abschluss-Check (auf einem Gerät):**
```bash
git fetch --all
git branch -a | grep bridge/task        # alle Hop-Branches sichtbar?
# optional: jeden Branch der Reihe nach mergen und am Ende die Tests laufen lassen:
#   python -m pytest chain_demo/test_chain.py -q   -> [1,2,3] grün
```
**Erfolg = das Modul ist über 5 Hops + beide Geräte entstanden, jeder Branch baut
auf dem vorherigen auf, der Schlusstest ist grün.**

---

## Kette 3 — Overnight-Queue (autonomer Nacht-Lauf + Morgen-Digest)

**Was sie beweist:** der Overnight-Scheduler arbeitet eine Queue kleiner Goal-Loop-
Seeds seriell ab (der Reviewer im Goal-Loop läuft cross-device über `claude -p` auf
dem Peer) und schickt morgens **einen** Telegram-Digest.

Es gibt zwei Quellen:
- **Deine aktive Queue** in `docs/overnight/` (echte Doku-/CLI-Seeds) — die läuft
  im echten Nachtbetrieb.
- **Beispiel-Seeds** in `docs/overnight/_examples/` (Wegwerf-Mechanik-Übungen):
  `01-greet-util.md`, `02-slugify.md`, `03-roman-numerals.md`. Sie liegen im
  Unterordner und werden von der aktiven Queue **nicht** aufgegriffen.

**Erst Trockenlauf der aktiven Queue (startet nichts, sendet nichts):**
```bash
# auf A:
python bridge_overnight.py --dry-run --repo <REPO>
# listet die geplanten Seeds aus docs/overnight/ in alphabetischer Reihenfolge.
```

**Oder gezielt die Beispiel-Seeds testen:**
```bash
python bridge_overnight.py --dry-run --queue docs/overnight/_examples --repo <REPO>
```

**Manuell einmal voll durchlaufen lassen (zum Beobachten):**
```bash
python bridge_overnight.py --repo <REPO> --max-rounds 4
# arbeitet 01 -> 02 -> 03 ab, schreibt state/_overnight/runs/<stamp>.json,
# sendet am Ende den Telegram-Digest (sofern TELEGRAM_TOKEN/TELEGRAM_CHAT_ID gesetzt).
```

**Für echten Nachtbetrieb (Windows-Task, täglich 02:00):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_overnight.ps1 -Repo <REPO>
```

**Erfolg = am Morgen ein Digest "X accepted / Y eskaliert / Z Fehler", und für jeden
accepted Seed existiert das gebaute Modul; eskalierte Seeds haben eine
ESCALATION-*.md, die der Notifier separat gemeldet hat.**

> Seeds deaktivieren ohne Löschen: `.skip` anhängen oder nach `docs/overnight/_done/`
> verschieben. Eigene Seeds einfach als weitere `NN-name.md` ergänzen
> (Format: `## Ziel` / `## Done-Kriterien`).

---

## Reihenfolge-Empfehlung

1. **Kette 1** zuerst — beweist die Mechanik deterministisch in Minuten.
2. **Kette 2** danach — echtes Cross-Device-Bauen, sichtbar an den Branches.
3. **Kette 3** zuletzt — autonomer Nachtbetrieb, sobald 1+2 sauber laufen.

## Beobachten während der Läufe

```bash
python bridge_status.py --watch       # Tasks/Loops/Eskalationen/Poller-Liveness je Lane
```
Zeigt live, was geclaimt/verarbeitet wird und ob ein Poller hängt.
