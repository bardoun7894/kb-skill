---
name: kb-compile
description: Compile new daily conversation logs into structured knowledge articles under knowledge/concepts and knowledge/connections. Use when the user asks to compile the knowledge base, after a long coding session, or when daily/ has uncompiled logs. Automatic compilation also runs after 6pm via the SessionEnd hook installed by kb-setup.
allowed-tools: Bash Read Glob
---

# kb-compile — compile conversation logs into the knowledge base

This skill is a thin wrapper around the project-local `scripts/compile.py`. It runs the Claude Agent SDK compiler that turns `daily/YYYY-MM-DD.md` conversation logs into concept and connection articles in `knowledge/`.

## Prerequisites

The project must already be initialized by `/kb-setup`. If `ai-knowledge-base/scripts/compile.py` does not exist, ask the user to run `/kb-setup` first.

## Steps

1. **Find the KB root.** Walk up from the current working directory looking for a folder that contains `scripts/compile.py`, `knowledge/`, and `daily/`. By default it is `<project>/ai-knowledge-base/`. Stop at the project root (first ancestor with `.git/` or `.claude/`).

2. **Check for work.** Run the dry-run first so the user can see what will compile:
   ```bash
   uv run --directory <kb-root> python scripts/compile.py --dry-run
   ```
   If the output is "Nothing to compile — all daily logs are up to date.", stop and report that to the user. Do not proceed.

3. **Confirm and compile.** If there are files to compile, show the list to the user and ask for confirmation. On approval, run:
   ```bash
   uv run --directory <kb-root> python scripts/compile.py
   ```
   This invokes the Claude Agent SDK with `permission_mode=acceptEdits` and writes concept/connection articles directly. Each daily log costs roughly $0.45–$0.65 to compile.

4. **Report the result.** Parse the final line of stdout (`Compilation complete. Total cost: $X.XX`) and relay it to the user, along with the names of any new articles under `knowledge/concepts/` that did not exist before.

## Flags

Pass these through if the user mentions them:
- `--all` — force-recompile every daily log (expensive; confirm the cost first).
- `--file <path>` — compile a single specific log.
- `--dry-run` — show what would compile without running the compiler.
