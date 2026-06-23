"""Orchestrate the interactive dual-bridge setup pipeline."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TextIO

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cli_scout import Scout
from scripts.config_generator import generate_config
from scripts.config_validator import validate_config
from scripts.wizard import InteractiveWizard

REPO_ROOT = Path(__file__).resolve().parents[1]


def main(config_path: str | Path | None = None, stdout: TextIO | None = None) -> int:
    """Run Scout -> Wizard -> Generator -> Validator and write config.json."""
    out = stdout or sys.stdout
    target = Path(config_path) if config_path is not None else REPO_ROOT / "config.json"

    try:
        _status(out, "Setup startet.")

        _status(out, "Scout: suche lokale Agent-CLIs.")
        scout_result = Scout().detect()
        _print_scout_result(out, scout_result)

        _status(out, "Wizard: ermittle Node-Zuordnung.")
        wizard_result = InteractiveWizard().ask(scout_result)
        _status(
            out,
            f"Wizard: A={wizard_result['node_a']}, B={wizard_result['node_b']}.",
        )

        _status(out, "Generator: baue config.json.")
        config = generate_config(scout_result, wizard_result)

        _status(out, "Validator: pruefe Pflichtfelder und CLI-Kommandos.")
        validate_config(config)

        _write_config(target, config)
        _status(out, f"Fertig: config.json geschrieben: {target}")
        _status(out, "Bridge kann jetzt gestartet werden, z.B. mit: python scripts/handoff_poll.py --watch")
        return 0
    except Exception as exc:
        print(f"FEHLER: Setup abgebrochen: {exc}", file=out)
        return 1


def _print_scout_result(out: TextIO, scout_result: dict) -> None:
    for name in ("claude", "codex"):
        value = scout_result.get(name)
        if value:
            _status(out, f"Scout: {name} gefunden: {value}")
        else:
            print(f"WARNUNG: Scout: {name} nicht gefunden; Generator nutzt Fallback '{name}'.", file=out)


def _write_config(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _status(out: TextIO, message: str) -> None:
    print(f"[setup] {message}", file=out)


if __name__ == "__main__":
    raise SystemExit(main())
