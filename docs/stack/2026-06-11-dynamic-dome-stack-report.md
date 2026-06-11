# Stack-Bericht — dynamic-dome / DoMe Dynamics

> **Zweck:** Eine vollständige, stack-weite Karte über alle Repositories der
> Organisation `dynamic-dome`. Sie beschreibt *was* gebaut wird, *warum*, *was
> womit verbunden ist* und ist bewusst so geschrieben, dass **Agenten** (Claude,
> Codex, DCO-Worker) daraus den Stack verstehen, einordnen und damit arbeiten
> können.
>
> **Stand:** 2026-06-11 · **Quellbasis:** 54 Repos der Org `dynamic-dome`
> (GitHub-API-Metadaten + Repo-Beschreibungen) · `dual-bridge` zusätzlich
> **code-verifiziert** (voller Datei-Lesezugriff). Für alle anderen Repos stützt
> sich der Bericht auf Beschreibung, Sprache, Sichtbarkeit, Zeitstempel und die
> Querverweise aus den `dual-bridge`-Dokumenten. Stellen mit reiner Inferenz sind
> als _„(abgeleitet)"_ markiert.
>
> **Provenienz-Hinweis:** In dieser Session ist nur `dynamic-dome/dual-bridge`
> für vollen Datei-Lesezugriff freigeschaltet; die GitHub-Code-Suche indexiert die
> privaten Repos nicht. Tiefe je Repo lässt sich erhöhen, indem die jeweiligen
> Repos der Session hinzugefügt werden (siehe § „Lücken & nächste Vertiefung").

---

## 1. Executive Summary — der rote Faden

Der Stack ist **kein loser Haufen von Projekten, sondern eine sich selbst
orchestrierende Agenten-Werkstatt** mit drei Standbeinen und einem verbindenden
Nervensystem:

1. **Agentische Infrastruktur (das Herz).** Ein Multi-Maschinen-,
   Multi-Modell-Orchestrierungssystem: zwei Laptops (A/Claude, B/Codex), eine
   dateibasierte Bridge über Google Drive, ein zentraler Orchestrator (DCO) mit
   HTTP-Job-Queue, und ein wachsendes Plugin-/Skill-Ökosystem für Claude Code.
   Ziel: agentische Arbeit **robust, nachweisbar und unbeaufsichtigt** zwischen
   Maschinen und Modellen übergeben (build → review → eskalieren/akzeptieren).

2. **Wissens- & Gedächtnisschicht (das Langzeitgedächtnis).** Ein dreischichtiges
   Obsidian-LLM-Wiki (`dominic-wiki`), Kompetenz-Wiki, „living vault" und
   Memory-Spiegelung in Claude Codes nativen Speicher. Hier liegen Master-Pläne,
   Roadmaps und kuratiertes Wissen, aus denen die Agenten ihre Aufträge ziehen.

3. **Produkt- & Markenschicht (das Sichtbare).** Eine Computer-Vision-Produktlinie
   für automatisches Dart-Scoring (mehrere Generationen), ein DoMe-Dynamics-
   Design-System (Tokens, UI-Komponenten, Themes, Brand-Kit) und ein dualer
   Lebenslauf/CV-Auftritt (NDT/Mechatronik + AI/Systems).

Das verbindende Nervensystem ist die **Orchestrierungs-Spine**: DCO (Job-Quelle)
→ dual-bridge (Transport + Goal-Loop) → Codex/Claude-Adapter (Ausführung) →
Skill-/Plugin-/Graph-Werkzeuge (Wissens-Backbone) → Wiki (Ground Truth). Fast
alles andere im Stack ist entweder **Input** für diese Spine (Wiki, Roadmaps,
Skills) oder **Output/Ziel** ihrer Arbeit (Produkt-Repos, Brand-Repos).

**In einem Satz:** Du baust eine autonome, fail-closed abgesicherte Agenten-
Fabrik, die nachts und cross-device an deinen eigenen Repos arbeitet, ihr Wissen
aus einem kuratierten Wiki zieht und ihre Ergebnisse in Produkt- und Markenschicht
ausliefert.

---

## 2. Die Stack-Karte (Cluster & Verbindungen)

```
                       ┌─────────────────────────────────────────────┐
                       │   WISSEN / GEDÄCHTNIS  (Ground Truth, Input)  │
                       │  dominic-wiki · kompetenz-wiki · living-vault │
                       │  Erinnerung · wiki-graph-showcase             │
                       │  └─ Master-Pläne, Roadmaps, Specs, Seeds ─────┼──┐
                       └─────────────────────────────────────────────┘  │ liefert
                                                                          │ Aufträge
            ┌─────────────────────────────────────────────────────────┐ │ & Wissen
            │        ORCHESTRIERUNGS-SPINE  (das Nervensystem)          │◄┘
            │                                                            │
            │  dynamic-central-orchestrator (DCO)  ── HTTP /api ──┐      │
            │     │ Job-Queue, Status-Mapping, Token, Telegram    │      │
            │     ▼                                               ▼      │
            │  dual-bridge  ◄── Drive-Datei-Lanes ──►  job_poll (Worker) │
            │     │ Adapter: echo · codex · claude                       │
            │     │ Goal-Loop: build → review → escalate/accept          │
            │     ▼                                                       │
            │  orchestrated-loop / orchestrated-bridge                   │
            │     4-Rollen-Loop (Orchestrator/Researcher/Builder/Judge)  │
            │     + Pre-Tool-Use-Gate (Tripwire/Ledger/Verdikt)          │
            │                                                            │
            │  agent-orchestrator · multi-model-orchestrator · ToDoDcO   │
            └───────────────┬────────────────────────────┬───────────────┘
                            │ nutzt / pflegt              │ produziert für
              ┌─────────────▼──────────────┐  ┌───────────▼───────────────┐
              │  SKILL- & PLUGIN-BACKBONE   │  │   PRODUKT- & MARKENSCHICHT │
              │ skill-index · plugin-       │  │  Dart-Vision (8 Repos)     │
              │ knowledge-graph · bridge-   │  │  DoMe-UI/Brand (7 Repos)   │
              │ replay · Skillschmiede ·    │  │  cv-dynamic-dome · sparfuchs│
              │ claude-plugins-marketplace ·│  │  pulse                     │
              │ agentic-workflow-suite ·    │  └────────────────────────────┘
              │ crazy-professor · tool-     │
              │ usage-tracker · agentic-os ·│  ┌────────────────────────────┐
              │ agentic-memory · self-      │  │  SELF-IMPROVEMENT / LABOR   │
              │ improve* · inception-sandbox│  │  self-improve · selfimprove-│
              │ devil-advocate-swarms       │  │  loop · self-improving-     │
              └─────────────────────────────┘  │  agent(-v3) · test-repo ·  │
                                               │  dual-bridge-tools-lab     │
                                               └────────────────────────────┘
```

**Die fünf Cluster:**

| # | Cluster | Rolle im Stack | Repos (Anzahl) |
|---|---|---|---|
| A | **Orchestrierungs-Spine** | Nervensystem: Jobs verteilen, ausführen, prüfen | 8 |
| B | **Skill- & Plugin-Backbone** | Werkzeugkasten + Selbstverbesserung der Agenten | ~15 |
| C | **Wissen / Gedächtnis** | Ground Truth, Master-Pläne, kuratiertes Wissen | 5 |
| D | **Produkt: Dart-Vision (CV)** | Älteste Produktlinie, CV-Dartscoring | 9 |
| E | **Produkt: DoMe Brand / UI / CV** | Design-System, Marke, Lebenslauf, Tools | 9 |

(Restliche Repos: Workshops, Utilities, Test-Repos — siehe § 8.)

---

## 3. Cluster A — Die Orchestrierungs-Spine (das Herz)

Dies ist der am tiefsten ausgebaute und aktivste Teil des Stacks. Hier liegt die
eigentliche Innovation: **agentische Arbeit cross-device und cross-model robust
übergeben und nachweisbar machen.**

### 3.1 `dual-bridge` — die Handoff-Bridge ⭐ (code-verifiziert)

**Was:** Dateibasierte, **bidirektionale** Handoff-Bridge zwischen zwei
Laptop-Endpunkten (`claude@laptop-a`, `codex@laptop-b`) über den Google-Drive-
Sharepoint. Jeder Knoten **sendet UND empfängt** — Rolle, Modell und Richtung sind
reine Konfiguration (`DUAL_BRIDGE_ENDPOINT`), kein Code.

**Architektur:**
- **Zwei richtungsgetrennte Lanes** (`lane-A-to-B/`, `lane-B-to-A/`), je mit
  `outbox/ inbox/ _processed/ _errors/`. Eigener Claim-Pool je Richtung →
  Cross-Device-Claim-Race **strukturell ausgeschlossen** (`os.rename` ist nur
  lokal atomar).
- **Code liegt lokal, der Sharepoint trägt nur Daten** (Manifest §7), keine
  Secrets in Tasks. Verarbeitetes wird verschoben, nie gelöscht.
- **Adapter trennen Modell von Fachabsicht:** `echo` (Smoke, kein LLM), `codex`
  (echter `codex exec`, committet+pusht Branch `bridge/task-<id>`), `claude`
  (echter `claude -p`, reine Textantwort). Das Frontmatter-Feld `adapter` steuert,
  *welches Modell* läuft; das Feld `kind` (`implement`/`research`/`review`/`test`)
  steuert die *Fachabsicht*.

**Kernfunktionen (Skripte in `scripts/`):**
- `handoff_write.py` / `handoff_poll.py` / `handoff_collect.py` — die drei
  Grundbefehle (schreiben / claimen+verarbeiten / einsammeln), endpoint-relativ,
  auf A und B identisch.
- `loop_driver.py` — **Goal-Loop (Stufe 3):** offenes Ziel + Done-Kriterien,
  Build→Review-Runden, Reviewer-Verdikt, fail-closed Eskalation
  (`ESCALATION-<loop_id>.md`) mit Reseed-Resume und harter Continuity. Modi:
  `ping-pong` (Stufe 1), `build-review` (Stufe 2b), `goal-loop` (Stufe 3).
  `--merge-on-accept` mergt akzeptierte Loop-Branches in die Base (für abhängige
  Paketketten).
- `job_poll.py` — **DCO-HTTP-Job-Pull:** `DUAL_BRIDGE_TRANSPORT=http` claimt Jobs
  aus dem DCO (`GET /api/jobs/next`), fährt sie als Goal-Loop, meldet den rc
  zurück (`POST /api/jobs/<id>/result`). Der DCO mappt rc → finalen Status (Single
  Source of Truth).
- `bridge_status.py` — read-only Status-Dashboard (Tasks/Loops/Eskalationen/
  Liveness je Lane; text+json, `--watch`; schreibt nie).
- `bridge_notify.py` — Eskalations-Notifier per Telegram, idempotent (Dedup je
  `loop_id+reason`), mit HTTP-Härtung (permanente vs. transiente Fehler,
  cross-trigger-Retry ohne `sleep`).
- `bridge_overnight.py` — Overnight-Scheduler: arbeitet nachts eine Seed-Queue
  (`docs/overnight/*.md`) seriell ab, sendet morgens **einen** Telegram-Digest.
- `bridge_common.py` — zentrale Pfad-/Endpoint-/Lane-Auflösung (Source of Truth);
  `this_endpoint()` erkennt die Maschine per Hostname.
- Weitere: `latency_probe.py`, `live_mirror.py`, `idea_feeder.py`, `shadow_run.py`,
  `runners.py`, `bridge_transport.py`, diverse `diagnose-*` und `register_*.ps1`
  (Windows Scheduled Tasks: Watchdog, Notifier, Overnight, Jobpoll).

**Härtung (warum das robust ist):** `task_id`-Regex-Validierung gegen
Path-Traversal/Branch-Injection (invalide Tasks → `_errors/`-Quarantäne),
Repo-Allowlist für den Codex-Runner, P0-Crash-Requeue, Sibling-Surrender-Cleanup
gegen Doppel-Claims, Never-crash-Poller, Stale-PID-Schutz (Cmdline-Marker je
Poller). Geplant/teilgebaut: Env-Allowlist statt `os.environ.copy()`
(Anti-Cross-Key-Leak OpenAI↔Anthropic), zentrales `PYTHONUTF8`, NDJSON-Fallback-
Parser für `codex exec --json` (siehe `docs/plans/2026-06-02-tier1-quickwins-plan.md`).

**Stand:** Stufe 3 live cross-device bewiesen; 181 Tests grün. Zwei orthogonale
Transportwege: (1) Datei-Bridge (Drive, A↔B peer-to-peer), (2) HTTP-Bridge
(DCO→B). Test-Isolation über `conftest.py` (autouse, lenkt Bridge-Root/State auf
`tmp_path`).

### 3.2 `dynamic-central-orchestrator` (DCO) — die Job-Quelle ⭐ (sehr aktiv)

**Was (abgeleitet aus dual-bridge-Querverweisen):** Der zentrale Orchestrator mit
HTTP-API unter `https://bot.dynamic-dome.com/api`. Hält eine **Job-Queue**
(`jobs.claim_next`), vergibt Jobs an Worker (`worker_type=dual-bridge`) über
`GET /api/jobs/next`, nimmt Resultate über `POST /api/jobs/<id>/result` entgegen
und **mappt den Worker-rc auf den finalen Status** (`0=accepted→completed`,
`3=escalated→waiting_approval/escalated`, `2=config`, `1=other`). Bearer-Token-
Auth (`BRIDGE_API_TOKEN`), Repo-Allowlist (`BRIDGE_REPO_ALLOWLIST=…dynamic-dome/*`),
geteilte Telegram-Credentials. **7 offene Issues, zuletzt aktualisiert 2026-06-11**
— das aktivste Repo des Stacks und der natürliche „Kopf" der Spine.

**Rolle:** Single Source of Truth für Job-Status. Producer von Bridge-Jobs (Soll;
laut dual-bridge-PROJECT.md noch nicht voll als nativer Producer verdrahtet).

### 3.3 `ToDoDcO` — Aufgaben-/Backlog-Schicht für den DCO

**Was (abgeleitet):** Python, sehr jung (2026-06-04), aktiv (2026-06-09). Dem
Namen nach die Todo-/Backlog-Verwaltung, die den DCO mit Aufträgen speist
(„Quell-Todo `done`" taucht im dual-bridge-Briefing als DCO-Konzept auf).

### 3.4 `orchestrated-loop` — der 4-Rollen-Loop als Plugin (public)

**Was:** Adapter-agnostischer **4-Rollen-Loop**
(Orchestrator/Researcher/Builder/Judge) als **Claude-Code-Plugin** mit
persistierenden State-Dateien pro Projekt. Verallgemeinerung des Goal-Loop-Gedankens
in ein wiederverwendbares Plugin-Format.

### 3.5 `orchestrated-bridge` — das Pre-Tool-Use-Gate (public, Walking Skeleton)

**Was:** Pre-Tool-Use-Dual-Bridge-Gate. Kombiniert den 4-Rollen-Loop mit einem
**cross-device Review-Gate über die dual-bridge**. Das Sicherheitsmodell in drei
Worten: **Pre-Tool-Use = Tripwire, append-only Ledger = Lock, Bridge-Review-Verdikt
= Evidence.** Das ist der Versuch, agentische Tool-Ausführung *vor* dem Zugriff
abzufangen und gegen ein externes (cross-device) Verdikt abzusichern.

### 3.6 `agent-orchestrator` (+ `-plugin`, `multi-model-orchestrator-plugin`)

**Was:** Autonomer **Meta-Agent-Orchestrator**: Claude Opus orchestriert einen
Haiku-Brainstormer, NotebookLM-RAG und Codex-Instanzen. Die frühe (März 2026)
Inkarnation der Multi-Modell-Idee, die später in DCO + dual-bridge professionalisiert
wurde. `agent-orchestrator-plugin` und `multi-model-orchestrator-plugin` sind die
Plugin-Verpackungen.

> **Verbindung:** Cluster A ist eine **Evolutionslinie** — von früher Skript-/
> Shell-Orchestrierung (`agent-orchestrator`, März) über das Goal-Loop-Fundament
> (`dual-bridge`, Mai) zum zentralen Queue-Modell (`DCO` + `job_poll`) und der
> generalisierten Plugin-Form (`orchestrated-loop`/`-bridge`). Wer hier arbeitet,
> sollte `dual-bridge` als Referenz-Implementierung und den DCO als Status-Autorität
> behandeln.

---

## 4. Cluster B — Skill- & Plugin-Backbone (Werkzeug + Selbstverbesserung)

Damit die Spine nicht blind arbeitet, gibt es eine Schicht, die **die Werkzeuge der
Agenten selbst katalogisiert, prüft und verbessert.** Drei dieser Repos wurden am
**2026-06-06 als koordinierte „Bau-Task 1/3, 2/3, 3/3"-Trilogie** angelegt — sie
gehören zusammen und sind das jüngste Investment in den Backbone:

### 4.1 Die Bau-Task-Trilogie (2026-06-06)

- **`skill-index` (Bau-Task 1/3):** Liest alle `SKILL.md`, baut einen
  durchsuchbaren **JSON+MD-Index mit harter Gate-Extraktion** und
  Dubletten-Clustering. → Der Katalog „welche Skills gibt es, was triggert sie".
- **`bridge-replay` (Bau-Task 2/3):** Bridge-Job-Replay & **Determinismus-Harness**
  — spielt abgeschlossene dual-bridge-Läufe deterministisch nach und prüft
  Verdikt-/Reseed-Stabilität. → Die Qualitätssicherung für die Spine.
- **`plugin-knowledge-graph` (Bau-Task 3/3):** **Living Plugin Knowledge Graph v1**
  — Graph über Plugins/Skills/MCP-Tools/Pfade/Überschneidungen, nutzt `skill-index`
  als Input. → Die „Map der Werkzeuge", genau die Art Übersicht, die dieser Bericht
  für Repos ist.

> Diese drei sind selbst über die dual-bridge gebaut worden („Dual-Bridge Bau-Task")
> — der Stack baut also bereits **mit sich selbst an sich selbst.**

### 4.2 Skill-/Plugin-Quellen & Marktplatz

- **`Skillschmiede`** — „repo für meine skills", die Skill-Werkstatt/Schmiede.
- **`claude-plugins-marketplace`** — Claude-Code-Plugins-Marktplatz unter
  dynamic-dome (Distribution).
- **`agentic-workflow-suite`** (public) — Claude-Code-Skill, der rohe Ideen,
  Screenshots, Sprachnotizen oder Inbox-Dateien in **konkrete agentische
  Workflow-Blueprints** übersetzt (Trigger, Schritte, Verifikation, Fehlerpfade +
  Empfehlung Skill/Command/Hook/MCP). Das „Meta-Skill", das neue Skills entwirft.
- **`crazy-professor`** (public) — Divergenz-Generator für kreative Ideenfindung,
  Claude-Code-Plugin mit drei „unhinged voices". Der kreative Gegenpol zur
  strengen Loop-Logik.
- **`tool-usage-tracker`** — trackt Tool-Nutzung (Telemetrie für den Backbone,
  abgeleitet).
- **`notebooklm-plugin`** (archiviert) — NotebookLM-Anbindung; lebt operativ als
  Scheduled Tasks weiter (Auth-Refresh alle 20 min, Boot-Login), siehe
  `docs/BETRIEB-UEBERSICHT.md`.

### 4.3 Agentic OS & Selbstverbesserung

- **`agentic-os`** — die agentische Betriebssystem-Basis (Shell), aktiv gepflegt.
- **`agentic-memory`** — Companion-Plugin zu agentic-os: Einweg-Spiegel
  allowlisteter Identitäts-Dateien in Claude Codes **nativen Memory** (v0.1). Die
  Brücke zwischen Wissensschicht (Cluster C) und Laufzeit-Gedächtnis der Agenten.
- **`self-improve`, `selfimproveloop`, `self-improving-agent`,
  `self-improving-agent-v3`** — die Selbstverbesserungs-Experimentierreihe
  (März 2026). `-v3` = „self-improving-codex". Frühe Loops, aus denen die heutige
  Goal-Loop-Disziplin gereift ist.
- **`inception-sandbox`, `devil-advocate-swarms`** — Experimentierfelder
  (rekursive Agenten / Advocatus-Diaboli-Schwärme zur adversen Prüfung).
- **`dual-bridge-tools-lab`** — Werkzeug-Labor rund um die Bridge.

---

## 5. Cluster C — Wissen & Gedächtnis (Ground Truth, „Datenrepos")

Das sind die **Datenrepos**, nach denen ausdrücklich gefragt war. Sie sind der
*Input* der Spine: Master-Pläne, Roadmaps und Specs leben hier, und die Agenten
ziehen ihre Aufträge daraus.

- **`dominic-wiki`** ⭐ — **Obsidian-LLM-Wiki, dreischichtiges Vault**
  (`raw/` immutable Rohquellen | `wiki/` LLM-gepflegte Markdown-Schicht | `schema`).
  Kuratierte Wissensbasis zwischen unveränderlichen Rohquellen und einer von LLMs
  gepflegten Ebene. **Sehr aktiv (2026-06-10).** Hier liegen u.a. der
  `dual-bridge-master-plan` und die `stack-evolution-master-roadmap` (von der
  dual-bridge's Tier-1-Quickwins-Plan abgeleitet ist) — d.h. **dieses Wiki steuert
  faktisch die Roadmap des ganzen Stacks.**
- **`kompetenz-wiki`** — Kompetenz-/Skill-Wissensbasis (Python-getrieben).
- **`living-vault`** — „lebendiges" Vault (kontinuierlich gepflegte Wissensablage,
  abgeleitet).
- **`Erinnerung`** („myMemory") — frühes Memory-Projekt (JS, Dez 2025); Default-
  Branch noch `claude/initial-setup-*` → Proof-of-Concept-Stadium.
- **`wiki-graph-showcase`** — statisches **three.js-Showcase** eines kuratierten
  Astrophysik-Wissensgraphen aus dem Obsidian-Wiki (Crab-Nebula- + Dynamic-Dome-
  Themes, Gold-Mode-Slider). Die sichtbare/präsentierbare Form der Wissensschicht.

> **Verbindung:** `dominic-wiki` → (Master-Plan/Roadmap) → `dual-bridge`-Specs/Pläne
> → DCO-Jobs → Ausführung. `agentic-memory` spiegelt Teile dieser Schicht in den
> Laufzeit-Speicher der Agenten. `plugin-knowledge-graph` und `wiki-graph-showcase`
> sind zwei Graph-Sichten (Werkzeuge bzw. Wissen).

---

## 6. Cluster D — Produktlinie Dart-Vision (Computer Vision)

Die **älteste** Linie (ab August 2025) und der ursprüngliche Produktkern: ein
System, das per **Computer Vision** automatisch Dartwürfe erkennt und zählt. Viele
Generationen/Experimente zeugen von iterativer Produktentwicklung:

| Repo | Sprache | Stand | Rolle (abgeleitet) |
|---|---|---|---|
| `dart-vision-system` | Python | public, ⭐1 | Aktuellste „offizielle" Generation: automatic dart detection & scoring |
| `dart_vision_mvp` | Python | privat | MVP-Stand |
| `dart-vision-claude` | Python | public | Lokal gehostete Dart-App (Claude-Generation) |
| `CPU_basiertes_computer_vision_system` | Python | privat | CPU-only-CV-Ansatz (ohne GPU) |
| `Dart_cv` | Python | privat | CV-Kern/Experiment |
| `Darts_tracker-2.0` | Python | public | Tracker-Generation 2.0 |
| `darts_tracker_MAM.2.2.25` | Python | public | datierter Tracker-Stand (MAM.2.2.25) |
| `TracknScore_old_version` | Python | privat | Archiv älterer Versuche |
| `Darts-by-gpt` | TypeScript | privat | GPT-getriebene Variante (Web/TS) |

> **Einordnung für Agenten:** Diese Repos sind überwiegend *historisch/iterativ*.
> `dart-vision-system` ist der wahrscheinliche Kandidat für „aktiver Produktkern";
> die übrigen sind Vorgänger/Experimente. Bei Arbeit hier zuerst klären, welche
> Generation kanonisch ist (nicht über alle gleichzeitig arbeiten).

---

## 7. Cluster E — DoMe Dynamics: Brand, UI & CV

Die **Marken- und Auslieferungsschicht**. „DoMe Dynamics" ist die persönliche
Marke; hier liegt ein vollständiges, token-getriebenes Design-System plus
Self-Branding/CV.

**Design-System & UI:**
- `dome-ui-foundation-starter` (TS) — DoMe UI Foundation + token-getriebener
  React-UI-Starter (DTCG-Tokens, Token-Packs, Storybook).
- `dome-ui-starter` (TS) — DoMe-UI-**Komponentenbibliothek**
  (`@dynamic-dome/tokens` + `@dynamic-dome/ui`), 17 Komponenten, zwei Theme-Welten
  (Website Gold/Neon + Miniapp Organic Obsidian Glow), Storybook-verifiziert.
- `dome-theme-blueprint` (CSS) — semantische Design-Tokens, vier Edition-Themes
  (Core Gold, Water, Fire, Mono Lab).
- `dome-dynamics-brand-transfer-kit` (CSS) — Motion-Branding, Theme-System,
  Design-Lab-Showroom.
- `dome-dynamics-brand` / `dome-dynamics-showcase` — Marken-Assets bzw.
  TS-Showcase.

**Brand-Automatisierung (Verbindung zur Spine):**
- `dome-brand-asset-extractor-agent` (Python) — **DoMe-Dynamics-Brand-Asset-
  Intake-Agent:** extrahiert/sortiert/preview't Assets aus Websites, Logos, SVGs,
  Bildern und Logo-Videos. Das ist ein **agentisches Werkzeug**, das den
  Brand-Cluster mit der Agenten-Infrastruktur verbindet.

**Lebenslauf / Self-Branding:**
- `cv-dynamic-dome` (CSS) — **dualer CV** (NDT/Mechatronik + AI/Systems) auf
  Cloudflare Pages mit Access-OTP-Gate. Verrät den fachlichen Hintergrund:
  zerstörungsfreie Prüfung/Mechatronik **plus** AI/Systems.
- `cv-proof-dynamic-dome` — Proof-/Beleg-Variante des CV.

> **Verbindung:** Das verfügbare Indeed-/Gmail-/Calendar-MCP-Toolset deutet auf
> einen Job-/Karriere-Workflow hin, den die CV-Repos bedienen _(abgeleitet)_.

---

## 8. Restliche Repos (Workshops, Utilities, Test)

- `dynamic-claude-code-workshop` (public, HTML) — 3-Session-Hands-on-Workshop für
  erfahrene Devs: CLI, Ökosystem, fortgeschrittene Multi-Agent-Patterns. Du gibst
  dein Wissen über den Stack also auch als Schulung weiter.
- `dynamic-workshop` (public, HTML) — Workshop-Material.
- `sparfuchs` (Python) — Supermarkt-Preisvergleich Deutschland mit automatischen
  Deal-Alerts per Telegram. Eigenständiges Utility, teilt aber das **Telegram-Alert-
  Pattern** mit dual-bridge's Notifier.
- `pulse` (Python) — _(Zweck unklar; abgeleitet: Monitoring/Heartbeat)_.
- `test-repo` — bewusstes Wegwerf-Repo, Ziel für Bridge-/Codex-Live-Tests
  (codex darf dort echt klonen/branchen/pushen). **Kein Produktiv-Repo.**
- `cv-proof-dynamic-dome` — siehe Cluster E.

---

## 9. Querschnitt: wiederkehrende Muster & Prinzipien

Der Stack ist erstaunlich kohärent. Diese Prinzipien tauchen cluster-übergreifend
auf und sind das eigentliche „Betriebssystem" deiner Arbeitsweise:

1. **Konfiguration statt Code für Rolle/Richtung/Modell.** (dual-bridge: Endpoint;
   Adapter trennt Modell von Absicht.) Symmetrische, umkehrbare Systeme.
2. **Fail-closed + Eskalation an den Owner.** Lieber sauber stoppen und
   eskalieren (Telegram) als still falsch weiterlaufen. Reseed-Resume mit
   Continuity.
3. **Nachweis statt Selbstbericht.** „Mechanik ≠ Vertragstreue" (P006/P007):
   Ergebnisse werden byte-genau gegen `git show origin/<branch>` verifiziert,
   nicht geglaubt. `bridge-replay` härtet das per Determinismus-Check.
4. **Daten ≠ Code ≠ Secrets.** Sharepoint trägt nur Daten; keine Secrets in Tasks;
   Env-Allowlist gegen Cross-Key-Leaks; Verarbeitetes wird verschoben, nie gelöscht.
5. **Read-mostly & Dry-Run-Pflicht.** Status-Dashboards schreiben nie; Scheduled
   Tasks nie blind aktivieren (immer erst `--dry-run`).
6. **Drei-Schichten-Doku-Disziplin.** `AGENTS.md` (Laufzeit) / `HOW-TO-USE.md`
   (Befehle) / `README.md` (Vollreferenz) / `docs/PROJECT.md` (Summary) — nicht
   duplizieren, an genau einer Stelle pflegen.
7. **Deutsch für Kommunikation, Englisch für Code/Dateinamen.**
8. **Telegram als Owner-Kanal.** Eskalationen, Overnight-Digests, Deal-Alerts.
9. **Idempotenz & Singleton-Locks.** Dedup je Schlüssel, Stale-PID-Schutz,
   Crash-Requeue — gebaut für unbeaufsichtigten Dauerbetrieb.

---

## 10. Für Agenten: womit ihr rechnen müsst und arbeiten könnt

Wer als Agent in diesem Stack arbeitet, sollte Folgendes als gegeben annehmen:

**Topologie & Betrieb**
- Es gibt **zwei Maschinen** (A = `claude@laptop-a` = Reviewer-Knoten;
  B = `codex@laptop-b` = Builder-Knoten). Endpoint-Namen sind **Lane-Rollen, nicht
  Hardware** — beide Rollen dürfen auf einer Maschine laufen, getrennt durch
  Singleton-Locks.
- Zwei Transportwege: **Datei-Bridge** (Google Drive, A↔B) und **HTTP-Bridge**
  (DCO→B). Der **DCO ist die Status-Autorität** — ein Worker erzwingt nie einen
  Status, er meldet nur den rc.
- **Ground Truth vor jeder Änderung:** Spec+Plan lesen → Tests laufen lassen
  (`cd scripts && python -X utf8 -m pytest -q`, erwartet grün) → read-only
  Snapshot (`python scripts/bridge_status.py`) → erst dann ändern.

**Harte Regeln (nicht verhandelbar)**
- Sharepoint = nur Daten. Keine Secrets in Tasks. Verarbeitetes verschieben, nie
  löschen. Kein `git add -A` in dual-bridge — immer explizit stagen.
- Tests **nie** gegen echten Sharepoint/State (conftest erzwingt `tmp_path`).
- Scheduled Tasks nie blind aktivieren — erst `--dry-run`.
- Zwei Timeout-Schranken (`round_timeout` außen, `codex_timeout` innen) gemeinsam
  setzen — es greift die kleinste.

**Was ihr an Werkzeug habt**
- Adapter `echo`/`codex`/`claude`; Goal-Loop mit Verdikt+Eskalation; Status-,
  Notify- und Overnight-Skripte; Skill-Index + Knowledge-Graph als Werkzeug-Katalog;
  bridge-replay als Determinismus-Check; das Wiki als Auftrags-/Wissensquelle.
- MCP-seitig in dieser Umgebung sichtbar: GitHub, Google Drive/Gmail/Calendar,
  Craft, tldraw/Excalidraw, Indeed, Zapier — d.h. der Stack ist auf
  Wissens-, Office- und Job-Automatisierung ausgelegt.

**Womit ihr rechnen müsst (Stolperfallen, dokumentiert)**
- Windows-Subprocess-PATH-Falle (`codex` nicht im Worker-PATH → ~5s-Abbruch);
  Lösung `DUAL_BRIDGE_CODEX_BIN`.
- codex-exec-Hang (`%TEMP%`-Sandbox + ererbter SessionStart-Hook).
- Seed-Format: Goal-Loop verlangt `## Ziel` + `## Done-Kriterien`; roher Fließtext
  wird in `job_poll.ensure_seed_structure()` gewrappt.
- Abhängige Paketketten akkumulieren nicht von selbst — A muss vor B's Clone in die
  Base gemergt sein (`--merge-on-accept`).

---

## 11. Roadmap — was auf den Stack zukommt

Aus `docs/PROJECT.md`, dem Tier-1-Quickwins-Plan und der Cluster-Aktivität:

**Kurzfristig (in Arbeit)**
- DCO-Queue-Anbindung als nativer Bridge-Job-Producer fertig verdrahten (heute
  skizziert/teilgebaut).
- Overnight- und Notifier-Scheduled-Tasks nach Dry-Run produktiv aktivieren.
- Tier-1-Härtungen abschließen: NDJSON-Fallback-Parser, zentrales `PYTHONUTF8`,
  Env-Allowlist gegen Cross-Key-Leaks.
- Bau-Task-Trilogie (`skill-index`/`bridge-replay`/`plugin-knowledge-graph`)
  zu einem geschlossenen Werkzeug-Backbone zusammenführen.

**Mittelfristig (Richtung)**
- HTTP-Job-Pull nur ausbauen, wenn Drive-Latenz oder N-Worker-Skalierung real zum
  Problem wird (bewusst nachfrage-getrieben).
- Der „Living Plugin Knowledge Graph" als zentrale Werkzeug-Map; `agentic-memory`
  als stehende Brücke Wiki→Laufzeit-Speicher.
- Marken-/Produktschicht stärker agentisch bedienen (`dome-brand-asset-extractor-agent`
  als Muster).

**Strategische Richtung (abgeleitet aus der Gesamtform):** Von „zwei Laptops, die
sich Dateien schicken" zu einer **zentral orchestrierten, sich selbst
katalogisierenden und selbst verbessernden Agenten-Fabrik**, die ihr Wissen aus
einem kuratierten Wiki zieht, nachts unbeaufsichtigt an den eigenen Repos baut und
fail-closed an den Owner eskaliert.

---

## 12. Lücken & nächste Vertiefung

**Was dieser Bericht sicher weiß (code-verifiziert):** der gesamte
`dual-bridge`-Teil (Architektur, Skripte, Härtung, Betrieb, Roadmap-Plan).

**Was beschreibungsbasiert/abgeleitet ist:** alles zu den anderen 53 Repos. Die
Beschreibungen sind aussagekräftig, aber Funktions-Details, interne Architektur und
die genauen „eigens entworfenen Skills" pro Repo lassen sich nur aus den Repos
selbst gewinnen.

**So vertiefen:** Diese Session hat nur `dual-bridge` für Datei-Lesezugriff
freigeschaltet (GitHub-Code-Suche indexiert die privaten Repos nicht). Um den
Bericht je Cluster auf Code-Ebene zu vertiefen, die Ziel-Repos der Session
hinzufügen — empfohlene Reihenfolge nach Hebelwirkung:

1. `dynamic-central-orchestrator` (der Kopf der Spine, höchste Aktivität).
2. `skill-index` + `plugin-knowledge-graph` + `bridge-replay` (der Werkzeug-Backbone).
3. `dominic-wiki` (die Roadmap-/Wissensquelle, die alles steuert).
4. `orchestrated-loop` + `orchestrated-bridge` (die generalisierte Loop-Form).
5. `agentic-os` + `agentic-memory` (die OS-/Memory-Basis).

Mit Zugriff auf diese fünf Gruppen ließe sich aus diesem Bericht eine echte,
code-verifizierte **Stack-Map mit Funktions- und Skill-Inventar pro Repo** machen
— der natürliche v2 dieses Dokuments.

---

## Anhang — Vollständige Repo-Liste (54)

| Repo | Cluster | Sprache | Sichtbar | Erstellt | Zuletzt |
|---|---|---|---|---|---|
| dual-bridge | A Spine | Python | privat | 2026-05-30 | 2026-06-09 |
| dynamic-central-orchestrator | A Spine | Python | privat | 2026-04-17 | 2026-06-11 |
| ToDoDcO | A Spine | Python | privat | 2026-06-04 | 2026-06-09 |
| orchestrated-loop | A Spine | Python | public | 2026-05-12 | 2026-05-13 |
| orchestrated-bridge | A Spine | Python | public | 2026-05-31 | 2026-06-01 |
| agent-orchestrator | A Spine | — | public | 2026-03-27 | 2026-03-27 |
| agent-orchestrator-plugin | A Spine | Shell | public | 2026-03-28 | 2026-04-30 |
| multi-model-orchestrator-plugin | A Spine | Shell | privat | 2026-03-27 | 2026-03-27 |
| skill-index | B Backbone | Python | privat | 2026-06-06 | 2026-06-06 |
| bridge-replay | B Backbone | Python | privat | 2026-06-06 | 2026-06-06 |
| plugin-knowledge-graph | B Backbone | Python | privat | 2026-06-06 | 2026-06-06 |
| dual-bridge-tools-lab | B Backbone | Python | privat | 2026-06-06 | 2026-06-06 |
| tool-usage-tracker | B Backbone | Python | privat | 2026-06-02 | 2026-06-05 |
| Skillschmiede | B Backbone | — | privat | 2026-03-23 | 2026-04-23 |
| claude-plugins-marketplace | B Backbone | — | public | 2026-05-12 | 2026-05-12 |
| agentic-workflow-suite | B Backbone | Python | public | 2026-04-30 | 2026-04-30 |
| crazy-professor | B Backbone | HTML | public | 2026-04-22 | 2026-06-03 |
| notebooklm-plugin | B Backbone | Shell | privat (archiv) | 2026-03-24 | 2026-04-23 |
| agentic-os | B Backbone | Shell | privat | 2026-03-20 | 2026-06-03 |
| agentic-memory | B Backbone | Shell | privat | 2026-04-22 | 2026-04-23 |
| self-improve | B Backbone | — | privat | 2026-03-25 | 2026-03-27 |
| selfimproveloop | B Backbone | Shell | privat | 2026-03-24 | 2026-04-23 |
| self-improving-agent | B Backbone | Shell | public | 2026-03-24 | 2026-03-27 |
| self-improving-agent-v3 | B Backbone | Python | privat | 2026-03-18 | 2026-04-11 |
| inception-sandbox | B Backbone | Shell | public | 2026-03-25 | 2026-04-30 |
| devil-advocate-swarms | B Backbone | Shell | public | 2026-03-25 | 2026-04-30 |
| dominic-wiki | C Wissen | Python | privat | 2026-04-17 | 2026-06-10 |
| kompetenz-wiki | C Wissen | Python | privat | 2026-05-10 | 2026-05-25 |
| living-vault | C Wissen | Python | privat | 2026-05-09 | 2026-05-29 |
| Erinnerung | C Wissen | JavaScript | privat | 2025-12-30 | 2026-04-11 |
| wiki-graph-showcase | C Wissen | Python | privat | 2026-05-16 | 2026-05-29 |
| dart-vision-system | D Dart | Python | public | 2025-12-22 | 2025-12-27 |
| dart_vision_mvp | D Dart | Python | privat | 2025-10-08 | 2026-04-11 |
| dart-vision-claude | D Dart | Python | public | 2026-03-11 | 2026-03-28 |
| CPU_basiertes_computer_vision_system | D Dart | Python | privat | 2025-10-08 | 2026-04-11 |
| Dart_cv | D Dart | Python | privat | 2025-09-11 | 2026-04-11 |
| Darts_tracker-2.0 | D Dart | Python | public | 2025-09-10 | 2025-09-11 |
| darts_tracker_MAM.2.2.25 | D Dart | Python | public | 2025-08-31 | 2025-09-02 |
| TracknScore_old_version | D Dart | Python | privat | 2025-09-02 | 2026-04-11 |
| Darts-by-gpt | D Dart | TypeScript | privat | 2025-09-11 | 2026-04-11 |
| dome-ui-foundation-starter | E Brand | TypeScript | privat | 2026-05-19 | 2026-05-25 |
| dome-ui-starter | E Brand | TypeScript | privat | 2026-05-12 | 2026-05-17 |
| dome-theme-blueprint | E Brand | CSS | privat | 2026-05-19 | 2026-05-19 |
| dome-dynamics-brand-transfer-kit | E Brand | CSS | privat | 2026-05-19 | 2026-05-19 |
| dome-dynamics-brand | E Brand | Python | privat | 2026-05-19 | 2026-05-20 |
| dome-dynamics-showcase | E Brand | TypeScript | privat | 2026-04-24 | 2026-05-26 |
| dome-brand-asset-extractor-agent | E Brand | Python | privat | 2026-05-19 | 2026-05-19 |
| cv-dynamic-dome | E Brand | CSS | privat | 2026-05-05 | 2026-05-17 |
| cv-proof-dynamic-dome | E Brand | CSS | privat | 2026-05-09 | 2026-05-15 |
| dynamic-claude-code-workshop | Misc | HTML | public | 2026-04-09 | 2026-04-09 |
| dynamic-workshop | Misc | HTML | public | 2026-04-01 | 2026-05-21 |
| sparfuchs | Misc | Python | privat | 2026-03-25 | 2026-04-24 |
| pulse | Misc | Python | privat | 2026-05-22 | 2026-06-05 |
| test-repo | Misc | — | privat | 2025-09-11 | 2026-06-04 |

_Erstellt 2026-06-11. Pflege-Hinweis: Dies ist ein Snapshot. Bei Stack-Änderungen
(neue Repos, Cluster-Verschiebungen) hier aktualisieren oder durch die
code-verifizierte v2 ersetzen._
