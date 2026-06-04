## Ziel
Ergänze `overnight_demo/text_util.py` um eine kleine, robuste `slugify`-Funktion (Wegwerf-Testziel), die einen Anzeigetext in einen URL-tauglichen Slug umwandelt.

## Done-Kriterien
- [ ] Eine Funktion `slugify(text: str) -> str` existiert in `overnight_demo/text_util.py`.
- [ ] Sie wandelt Leerzeichen in Bindestriche, schreibt klein und entfernt nicht-alphanumerische Zeichen (außer Bindestrich).
- [ ] Mehrfache/führende/abschließende Bindestriche werden zu genau einem bzw. entfernt (z. B. "  Hallo,  Welt! " -> "hallo-welt").
- [ ] Die Funktion hat einen Docstring mit mindestens einem Beispiel.
