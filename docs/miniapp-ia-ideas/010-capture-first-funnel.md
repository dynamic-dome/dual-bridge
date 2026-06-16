## Ziel

Mache das **Einfangen** zum Primärakt. Die App lebt in Telegram — der natürlichen
Capture-Oberfläche (Text/URL/Voice/Dokument/Foto landen als Captures in der Inbox).
Heute ist „Inbox" nur Tab #2 und Captures versanden im Status `unprocessed`. These:
die App als **Trichter „roh → geklärt → in Aktion verwandelt → erledigt"**. Vorne
das Einfangen, dahinter ein klarer Veredelungs-Fluss, der jeden Capture in einen
Auftrag, Reminder oder Todo überführt — nichts bleibt liegen.

## IA-Konzept

**Capture-first Startfläche = Trichter in Stufen:**
- **Roh** — neu eingefangene Captures (unprocessed), Typ-Icon + Preview.
- **Geklärt** — gesichtet, mit Notiz/Kategorie versehen, noch nicht verwandelt.
- **Verwandelt** — als Auftrag/Reminder/Todo rausgegangen (Link zum Ziel).
Jeder Capture hat **„Verwandeln in →"** (Auftrag · Reminder · Todo) als
Ein-Tap-Aktion; danach verlässt er den Trichter (wird `processed`).

**Leerer Trichter** = einladend, handlungsweisend: „Inbox leer. Schick was an den
Bot oder starte einen Auftrag." (kein leerer Schirm.)

**Verknüpfungen:**
- „Verwandeln" seedet die bestehenden Create-Flows (Compose-Preset / Reminder /
  Todo) mit dem Capture-Inhalt → schließt Capture und Aktion kurz.
- Suche/Palette bleiben global; Monitoring (Jobs/Ergebnisse) ist sekundär.
```
+--------------------------------------------------+
| (icon) EINGANG                  [ + erfassen ]    |
|--------------------------------------------------|
|  ROH (3)                                          |
|   [url]  "github.com/..."   -> Verwandeln in v    |
|   [txt]  "Idee: relay ..."  -> Verwandeln in v    |
|  GEKLAERT (1)                                     |
|   [voice] "Notiz Backup"    -> Reminder           |
|  VERWANDELT                                       |
|   [txt] -> Auftrag job7831 . [url] -> Todo        |
|--------------------------------------------------|
| [ Eingang ][ Arbeit ][ Ergebnisse ][ Mehr ]       |
+--------------------------------------------------+
```

**Signatur-Move:** der Capture-Lebenszyklus wird sichtbar — vom rohen Schnipsel zur
verwandelten Aktion; die Inbox ist kein Ablagestapel mehr, sondern ein Trichter.

## Done-Kriterien

- [ ] **Capture-first View** stellt Captures in Stufen dar (Roh/Geklärt/Verwandelt)
      aus `/captures?filter=...`; Default-Startfläche oder prominenter erster Tab.
- [ ] Jeder Capture hat **„Verwandeln in → Auftrag/Reminder/Todo"**, das den
      jeweiligen Create-Flow mit dem Capture-Inhalt vorbelegt (Compose nur Presets,
      Risk-Policy) und den Capture auf `processed` setzt.
- [ ] `index.html`/`js/app.js`: Eingang als Startfläche/erster Tab; Monitoring-Tabs
      sekundär; bestehende Aliases bleiben gültig.
- [ ] **Empty-State** mit handlungsweisendem Text + Erfassen-/Auftrag-CTA.
- [ ] **Funktions-Parität:** Mapping alt→neu im PR; alle heutigen Inbox-Filter/
      -Detail-Funktionen bleiben; Verwandlungen erzeugen über bestehende Endpunkte.
- [ ] Tests grün/erweitert; a11y: Trichter als Liste, Typ nicht nur per Icon-Farbe,
      reduced-motion.

## Leitplanken

- Telegram-Mini-App: nutzt die Capture-Typen (Text/URL/Voice/Doc/Foto); safe-area.
- **Keine Funktion geht verloren** — Inbox wird zum Trichter, Filter/Detail bleiben.
- Deep-Link-Aliases bleiben funktionsfähig.
- Risk-Policy: „Verwandeln in Auftrag" nutzt nur erlaubte Presets.
- a11y: Empty-States geben Richtung, aktive Verben, sichtbarer Fokus.

## Herkunft

IA-Loop, Zyklus 5, 2026-06-16. Adressiert das Versanden von Captures (Inbox als
Stapel) und bündelt die Verwandlung in Aktionen. Input-getriebener Trichter —
geerdet in den Telegram-Capture-Typen + `processed`-Status; Gegenstück zur
output-getriebenen Triage (002) und zur Bau-Werkstatt (009).
