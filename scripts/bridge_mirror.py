"""b1 Ops-State-Mirror: spiegelt A-seitigen Loop-State read-only auf den Drive.

Der DCO/`/ops`-Konsolen-Knoten ist NICHT der Loop-Host (Entscheidung A) und sieht
darum die nur-lokal abgelegten LOOP-*.jsonl / ESCALATION-*.md / _overnight /
_notify nicht. Dieser Spiegel kopiert sie (read-only) in einen Drive-Unterordner
(``<bridge_root>/_ops-state-mirror/`` per Default), aus dem die Ops-Endpoints
lesen. Bleibt damit „Sharepoint traegt nur Daten" treu.

INVARIANTE: schreibt NUR in den Mirror, nie in den Source-State. Aufgeloeste
Loops/Eskalationen (in der Source verschwunden) werden im Mirror entfernt, damit
die Konsole nie veraltete „offene" Eintraege zeigt.

Dual-runnable:
    python -m pytest scripts/test_bridge_mirror.py
    python scripts/bridge_mirror.py [--dry-run] [--state DIR] [--mirror DIR]
"""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

import bridge_common as bc

_TOP_PATTERNS = ("LOOP-*.jsonl", "ESCALATION-*.md")


def _resolve_state_dir() -> Path:
    """Source-State (lokal, A-seitig). DUAL_BRIDGE_STATE ueberschreibt — wie in
    bridge_status._resolve_state_dir, damit beide denselben Ordner sehen."""
    override = os.environ.get("DUAL_BRIDGE_STATE")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "state"


def default_mirror_root() -> Path:
    """Ziel auf dem Drive: ein dedizierter, von uns besessener Unterordner."""
    return bc.bridge_root() / "_ops-state-mirror"


def mirror_state(state_dir: Path, mirror_root: Path, dry_run: bool = False) -> dict:
    """Spiegele den read-only Loop-State nach mirror_root. Mutiert NIE state_dir."""
    state_dir = Path(state_dir).resolve()
    mirror_root = Path(mirror_root).resolve()
    # Disjunkt-Guard (Codex-Fix): mirror_root darf weder state_dir noch ein
    # Eltern-/Kind-Pfad davon sein — sonst koennte der Prune Source-Dateien
    # loeschen. is_relative_to(self) deckt Gleichheit mit ab.
    if state_dir.is_relative_to(mirror_root) or mirror_root.is_relative_to(state_dir):
        raise ValueError(
            f"mirror_root ({mirror_root}) und state_dir ({state_dir}) duerfen sich "
            "nicht ueberlappen — refuse (Prune koennte Source loeschen).")

    # (dst -> src) fuer alle zu spiegelnden Dateien.
    sources: dict[Path, Path] = {}
    top_names: set[str] = set()
    for pattern in _TOP_PATTERNS:
        for p in sorted(state_dir.glob(pattern)):
            sources[mirror_root / p.name] = p
            top_names.add(p.name)
    runs = state_dir / "_overnight" / "runs"
    if runs.is_dir():
        for p in sorted(runs.glob("*.json")):
            sources[mirror_root / "_overnight" / "runs" / p.name] = p
    notify = state_dir / "_notify"
    if notify.is_dir():
        for p in sorted(notify.glob("*.json")):
            sources[mirror_root / "_notify" / p.name] = p

    # Prune: top-level Mirror-Dateien, die es in der Source nicht mehr gibt
    # (aufgeloeste Loops/Eskalationen) — sonst zeigt die Konsole Geister.
    pruned = 0
    if mirror_root.is_dir():
        for pattern in _TOP_PATTERNS:
            for m in mirror_root.glob(pattern):
                if m.name not in top_names:
                    pruned += 1
                    if not dry_run:
                        m.unlink()

    copied = 0
    if not dry_run:
        for dst, src in sources.items():
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Symlink-sicher (Codex-Fix): einem geplanten Ziel-Symlink NIE folgen
            # (sonst schriebe copy2 ausserhalb des Mirrors).
            if dst.is_symlink():
                dst.unlink()
            shutil.copy2(src, dst)
            copied += 1

    return {
        "planned": len(sources),
        "copied": copied,
        "pruned": pruned,
        "dry_run": dry_run,
        "state_dir": str(state_dir),
        "mirror_root": str(mirror_root),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="b1 Ops-State-Mirror (read-only Spiegel).")
    ap.add_argument("--state", default=None,
                    help="Source-State-Dir (Default: DUAL_BRIDGE_STATE bzw. scripts/state).")
    ap.add_argument("--mirror", default=None,
                    help="Ziel-Mirror-Dir (Default: <bridge_root>/_ops-state-mirror).")
    ap.add_argument("--dry-run", action="store_true", help="Nur planen, nichts schreiben.")
    args = ap.parse_args(argv)
    state_dir = Path(args.state) if args.state else _resolve_state_dir()
    mirror_root = Path(args.mirror) if args.mirror else default_mirror_root()
    s = mirror_state(state_dir, mirror_root, dry_run=args.dry_run)
    print(f"mirror: planned={s['planned']} copied={s['copied']} pruned={s['pruned']} "
          f"dry_run={s['dry_run']} -> {s['mirror_root']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
