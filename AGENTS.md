# AGENTS.md - dual-bridge

Agent-specific runtime guidance for this repository. User-facing docs and full
commands live in `HOW-TO-USE.md` and `README.md`; do not duplicate them here.

## Project

`dual-bridge` is a file-based, bidirectional handoff bridge between endpoints
(`claude@laptop-a`, `codex@laptop-b`) via the Google Drive sharepoint. Current
state: Stage 3 goal-loop + owner escalation is live-proven; DCO integration and
HTTP job pull remain later scopes.

## Required Reads

1. `CLAUDE.md` - project-specific agent rules and task commands.
2. `HOW-TO-USE.md` - user/agent index and current entry points.
3. `README.md` - full architecture, env vars, protocol, hardening.
4. Relevant spec/plan under `docs/superpowers/` before architecture changes.

## Ground Truth Before Changes

- Run `git status --short` and do not overwrite unrelated user/agent drift.
- For code changes, inspect `scripts/conftest.py` before any pytest call; tests
  must use isolated `DUAL_BRIDGE_ROOT`/state, never the real sharepoint.
- For live-state context, use `python scripts/bridge_status.py`; it is read-only.
- Scheduled tasks (`register_*.ps1`) are never enabled blindly; run the matching
  `--dry-run` path first.

## Conventions

- Communicate in German; keep code identifiers and filenames in English.
- Sharepoint carries data only, never code or secrets.
- Processed bridge files move to `_processed/`/`_errors/`; do not delete them.
- Use explicit path staging for commits; never `git add -A` in this repo.
- Keep docs concise and source-of-truth separated: `AGENTS.md` for runtime
  guidance, `HOW-TO-USE.md` for commands, `README.md` for full reference,
  `docs/PROJECT.md` for the project summary.

## Important Paths

- `scripts/` - bridge scripts, adapters, loop driver, tests.
- `docs/overnight/` - goal-loop seed queue for the overnight scheduler.
- `docs/live-proofs/` - cross-device proof material and runbooks.
- `docs/superpowers/specs/` and `docs/superpowers/plans/` - approved designs
  and implementation plans.
