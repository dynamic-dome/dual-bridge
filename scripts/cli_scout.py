"""Detect locally installed agent CLIs."""
from __future__ import annotations

import shutil


class Scout:
    """Small helper for discovering supported CLI executables on PATH."""

    def detect(self) -> dict[str, str | None]:
        return {
            "claude": shutil.which("claude"),
            "codex": shutil.which("codex"),
        }
