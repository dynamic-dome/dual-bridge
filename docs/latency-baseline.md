# Dual-Bridge Latenz-Baseline

_Append-only. Eine Zeile pro Probe-Lauf._

- 2026-05-30T14:00:40 | DOME-DYNAMICS | n=2 ok, 0 timeout | min 1.0s · median 1.0s · avg 1.0s · max 1.0s | poll-gap unbekannt (B-seitig)
- 2026-05-30T14:06:28 | DOME-DYNAMICS | n=5 ok, 0 timeout | min 23.0s · median 27.6s · avg 28.4s · max 38.1s | poll-gap unbekannt (B-seitig)
- 2026-05-30T14:24:44 | DOME-DYNAMICS | n=30 ok, 0 timeout | min 22.0s · median 28.1s · avg 27.6s · max 31.1s | poll-gap unbekannt (B-seitig)

## Auswertung n=30 (2026-05-30, A=DOME-DYNAMICS ↔ B=K472HEXXZACKBUU, B-Poll-Intervall 2s)

| min | median | avg | p90 | p95 | max | stdev |
|---|---|---|---|---|---|---|
| 22.0s | 28.1s | 27.65s | 28.1s | 28.6s | 31.1s | **1.60s** |

**Befund:** Google Drive synct in einem sehr regelmäßigen ~28s-Takt. Sehr geringe
Streuung (stdev 1.6s, 16/30 exakt 28.1s, p95 ≈ Median). → ~28s ist eine **planbare
Konstante**, kein wackeliger Schätzwert. Der 38s-Ausreißer der ersten 5-Proben-Messung
war ein seltener Einzelfall (echter max bei n=30 nur 31.1s).

**Design-Konsequenz:** Träge, aber vorhersehbar. Ausreichend für Stage 1/2
(Codex-Calls, Overnight). Für interaktiv (Idee 3) später HTTP/Tunnel statt Drive.
