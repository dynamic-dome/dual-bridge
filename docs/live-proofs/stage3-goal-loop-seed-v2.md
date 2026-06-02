## Ziel
Add a small string utility module `greet_util.py` to the dual-bridge repo (throwaway live-proof target) that produces greeting strings.

## Done-Kriterien
- [ ] a function `greet(name: str) -> str` exists in `greet_util.py` and returns a non-empty greeting that contains the given name
- [ ] the function has a docstring
- [ ] the greeting is a German f-string of the exact form `f"Hallo, {name}!"` (double-quoted, snake_case function name, type-hinted) — judge this directly from the diff, no project reference needed
