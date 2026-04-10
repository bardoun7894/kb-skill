# kb-skill — setup

## One-time install

Prerequisites:
- `uv` (`brew install uv` on macOS)
- Claude Code with hook support

```bash
git clone <this-repo> ~/projects/kb-skill
cd ~/projects/kb-skill
./install.sh
```

`install.sh` copies the five `skills/kb-*/` folders into `~/.claude/skills/`. Claude Code picks them up automatically — no restart needed.

Verify the slash commands are discoverable:

```bash
ls ~/.claude/skills | grep kb-
```

You should see `kb-setup`, `kb-ingest`, `kb-compile`, `kb-query`, `kb-lint`.

## Per-project setup

In each project where you want a knowledge base:

```
/kb-setup
```

The wizard will:

1. Prompt for the KB folder name (default `ai-knowledge-base`)
2. Create the folder tree (`raw/`, `daily/`, `knowledge/{concepts,connections,sources,entities,qa}/`, `reports/`)
3. Copy the Python runtime (scripts + hooks + pyproject.toml + AGENTS.md) from the skill
4. Run `uv sync` to install dependencies
5. Merge `SessionStart` / `PreCompact` / `SessionEnd` hooks into `<project>/.claude/settings.local.json` (backup saved as `settings.local.json.bak-kb`)
6. Smoke-test the `SessionStart` hook

After this, conversations in that project auto-capture into `ai-knowledge-base/daily/YYYY-MM-DD.md` and compile automatically after 6pm local time, or on demand with `/kb-compile`.

## Upgrading an existing KB

Running `/kb-setup` against a project that already has `ai-knowledge-base/` is safe:

- `daily/`, `knowledge/`, `reports/`, and `state.json` are preserved
- `scripts/`, `hooks/`, `pyproject.toml`, `AGENTS.md` are replaced with the skill's latest versions
- Missing subdirs (`raw/`, `knowledge/sources/`, `knowledge/entities/`) are created
- `.claude/settings.local.json` is only touched if the hook paths need updating

## Uninstall

To remove the skills globally:

```bash
rm -rf ~/.claude/skills/kb-setup ~/.claude/skills/kb-ingest \
       ~/.claude/skills/kb-compile ~/.claude/skills/kb-query \
       ~/.claude/skills/kb-lint
```

To remove a project's KB without affecting the skills:

```bash
# from inside the project
rm -rf ai-knowledge-base
# then manually remove the "hooks" key from .claude/settings.local.json
```

The project's conversations that were already captured into `daily/` and compiled into `knowledge/` will be lost unless you back the folder up first.
