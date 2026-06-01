"""Stage-1 ping-pong loop tests. Isoliert, kein echtes Drive (conftest.py setzt
DUAL_BRIDGE_ROOT auf tmp + re-registriert Runner)."""
from __future__ import annotations

from pathlib import Path

import bridge_common as bc
import runners


def test_increment_runner_adds_one():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="3", fm={"payload": "3"}, workroot=None)
    assert res.status == "done"
    assert res.antwort.strip() == "4"


def test_increment_runner_rejects_non_numeric():
    runner = runners.RUNNERS["increment"]
    res = runner(auftrag="abc", fm={"payload": "abc"}, workroot=None)
    assert res.status == "error"
    assert res.error_text  # nicht-leer, kein stiller Default
