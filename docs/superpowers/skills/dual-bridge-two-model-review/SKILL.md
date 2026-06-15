---
name: dual-bridge-two-model-review
description: Use when a dual-bridge task needs a reusable verifier/builder workflow, a two-model code review loop, or a portable Codex/Claude review pattern
---

# Dual Bridge Two Model Review

## Overview

Use this skill to run the proven dual-bridge verifier/builder pattern as a
portable Superpowers workflow. The core rule is simple: one model builds, the
other model reviews, and progress is accepted only through explicit verdicts and
green local verification.

## When to Use

- A task asks for a verifier/builder, builder/reviewer, or two-model review loop.
- A change should be hardened by an independent model before merge.
- A project needs the dual-bridge pattern exported or reused outside the original
  loop seed.
- A relay-style open goal benefits from Codex and Claude alternating builder
  responsibility.

Do not use this for a single read-only review where no build loop is needed.

## Roles

| Builder adapter | Reviewer adapter | Use case |
|---|---|---|
| `codex` | `claude` | Default build-review / goal-loop path. |
| `claude-build` | `codex-review` | Symmetric path when Claude builds and Codex verifies. |
| `codex` then `claude-build` | opposite reviewer each round | `relay-loop`, where accepted rounds rotate the builder. |

Verdict markers are contract text, not prose suggestions:

- `VERDICT: accepted` means the step is accepted and the loop can advance.
- `VERDICT: rejected` means the same builder must address reviewer feedback.
- `VERDICT: escalate` means owner input or a dangerous/risky decision is needed.

## Workflow

1. Start from a clean repo snapshot: `git status --short`.
2. Run baseline verification from the repo root:
   `python -X utf8 -m pytest -q`.
3. Pick the smallest fitting loop:
   - Fixed goal with Done criteria:
     `python -X utf8 loop_driver.py --mode goal-loop --repo <repo> --max-rounds 4 --seed <seed.md>`
   - Open collaborative expansion:
     `python -X utf8 loop_driver.py --mode relay-loop --repo <repo> --adapter codex --max-rounds 4 --seed <seed.md>`
4. Keep reviewer prompts concrete: include the diff or artifact under review,
   the acceptance criteria or goal, and the three verdict markers.
5. Treat `rejected` feedback as the next builder brief. Do not rewrite it into a
   softer task unless the owner explicitly changes direction.
6. Before claiming completion or opening a PR, rerun:
   `python -X utf8 -m pytest -q`.

## Documentation DoD

When exporting or changing this pattern in `dual-bridge`, update both canonical
docs in the target repo:

- `docs/CHANGELOG.md`
- `docs/CAPABILITIES.md`

Never create or update a root `CHANGELOG.md` when `docs/CHANGELOG.md` exists.

## Common Mistakes

- Letting the builder self-accept. The reviewer must be the other model.
- Treating `VERDICT: escalate` as success. It is an explicit stop for owner input
  or risk resolution.
- Using `relay-loop` for fixed Done criteria. Use `goal-loop` when the target is
  already known.
- Updating only chat notes. The reusable skill and capability record must live in
  the repository.
