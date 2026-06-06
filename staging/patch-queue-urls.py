"""Patcht die 4 DCO-Eintraege (#7758-7761) mit den um Repo-URLs ergaenzten Texten.

Importiert die Single-Source-of-Truth aus queue-3-bridge-tasks.py, damit Datei und DB
nicht auseinanderlaufen. Idempotent: setzt nur Text, legt nichts neu an.
"""
import importlib.util
import sys

sys.path.insert(0, r"C:\Users\domes\dynamic_central_orchestrator")
import todos

spec = importlib.util.spec_from_file_location(
    "qbt", r"C:\Users\domes\AI\dual-bridge\staging\queue-3-bridge-tasks.py"
)
qbt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qbt)

MAPPING = {
    7758: qbt.PARENT_TEXT,
    7759: qbt.TASK1,
    7760: qbt.TASK2,
    7761: qbt.TASK3,
}

for tid, text in MAPPING.items():
    res = todos.edit(tid, text)
    ok = res is not None
    print(f"#{tid} edit -> {'OK' if ok else 'MISS'}  (url? {'github.com' in text})")
