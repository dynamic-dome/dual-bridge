"""Interactive lane assignment wizard."""
from __future__ import annotations


class InteractiveWizard:
    """Ask simple terminal questions to map agent CLIs onto bridge nodes."""

    _CLIS = ("claude", "codex")

    def ask(self, scout_result: dict) -> dict:
        """Return the selected lane mapping for node A and node B."""
        available = [
            name for name in self._CLIS
            if scout_result.get(name)
        ]

        if len(available) == 1:
            suggestion = self._suggest_from_single_cli(available[0])
            if self._confirm(suggestion):
                return suggestion

        while True:
            selected = input("Welcher Node ist A (laptop-a)? [0] Claude [1] Codex: ").strip()
            if selected == "0":
                mapping = {"node_a": "claude", "node_b": "codex"}
            elif selected == "1":
                mapping = {"node_a": "codex", "node_b": "claude"}
            else:
                continue

            if self._confirm(mapping):
                return mapping

    def _suggest_from_single_cli(self, cli_name: str) -> dict:
        if cli_name == "codex":
            return {"node_a": "claude", "node_b": "codex"}
        return {"node_a": "claude", "node_b": "codex"}

    def _confirm(self, mapping: dict) -> bool:
        answer = input(
            f"Zuweisung verwenden: A={mapping['node_a']}, B={mapping['node_b']}? [y/N]: "
        ).strip().lower()
        return answer in {"y", "yes", "j", "ja"}
