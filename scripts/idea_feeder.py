"""No-op markers for idea-feeder loop checks."""
from __future__ import annotations


def step_e2e() -> bool:
    """Return True when the e2e marker is present."""
    return True
