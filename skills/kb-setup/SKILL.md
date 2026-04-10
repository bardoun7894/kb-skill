---
name: kb-setup
description: Initialize or upgrade the personal knowledge base in a project. Creates the ai-knowledge-base/ folder with raw/, daily/, knowledge/ subtree, copies the runtime scripts and hooks, merges Claude Code SessionStart/PreCompact/SessionEnd hooks into the project's settings.local.json, and runs uv sync. Use when the user asks to install the knowledge base, set up kb-skill, or enable automatic conversation capture in a new project. Safe to re-run — it detects an existing KB and upgrades in place.
allowed-tools: Bash Read Write Edit Glob
---

# kb-setup — initialize or upgrade the knowledge base in a project

This skill installs the shared runtime (scripts + hooks) into the current project and wires up Claude Code hooks so future conversations auto-capture into a daily log. Running it a second time against an already-initialized project performs a safe in-place upgrade.

## What gets created

```
<project>/
├── .claude/
│   └── settings.local.json            # hooks merged in (never overwritten wholesale)
└── ai-knowledge-base/
    ├── raw/                            # manual document inbox (empty + .gitkeep)
    ├── daily/                          # auto-captured conversation logs
    ├── knowledge/
    │   ├── index.md                    # master catalog
    │   ├── log.md                      # append-only build log
    │   ├── concepts/                   # auto + manual
    │   ├── connections/                # auto
    │   ├── sources/                    # manual (ingest)
    │   ├── entities/                   # manual (ingest)
    │   └── qa/                         # from /kb-query --file-back
    ├── reports/                        # lint reports
    ├── scripts/                        # copied from the skill runtime
    ├── hooks/                          # copied from the skill runtime
    ├── pyproject.toml
    └── AGENTS.md
```

## Prerequisites

- `uv` installed (`which uv`). If missing, stop and tell the user to install it with `brew install uv`.
- The current working directory is a project root (has `.git/`, `.claude/`, or a reasonable anchor). If not, ask the user to run this from the project they want to initialize.

## Workflow

### 1. Locate the skill runtime source

The runtime lives alongside this `SKILL.md` at `<skill-dir>/runtime/`. Resolve `<skill-dir>` by looking at the path of this file — typically `~/.claude/skills/kb-setup/runtime/`. Confirm the following exist before going further:

- `<skill-dir>/runtime/scripts/compile.py`
- `<skill-dir>/runtime/hooks/session-end.py`
- `<skill-dir>/runtime/pyproject.toml`

If any are missing, stop and tell the user the skill is not installed correctly — they should re-run `install.sh` from the kb-skill repo.

### 2. Determine the target KB folder

Default target: `<cwd>/ai-knowledge-base/`. Ask the user once:

> "I'll install the knowledge base at `<cwd>/ai-knowledge-base/`. Press enter to accept, or type a different folder name (relative to the project root)."

Store the answer as `KB_NAME` (default `ai-knowledge-base`) and compute `KB_ROOT=<cwd>/<KB_NAME>`.

### 3. Detect existing KB and choose mode

Three cases:

- **No `KB_ROOT` exists** → fresh install.
- **`KB_ROOT` exists and contains `scripts/compile.py`** → upgrade in place. Keep `daily/`, `knowledge/`, `reports/`, and `state.json` intact. Only replace `scripts/`, `hooks/`, `pyproject.toml`, `AGENTS.md`, and create any missing subdirs (`raw/`, `knowledge/sources/`, `knowledge/entities/`).
- **`KB_ROOT` exists but does not look like a KB** → stop and ask the user whether to pick a different folder.

Announce the mode to the user before writing anything.

### 4. Create the folder tree

For both fresh and upgrade modes, ensure these exist (use `mkdir -p`, do not clobber existing files):

```
$KB_ROOT/raw
$KB_ROOT/daily
$KB_ROOT/knowledge/concepts
$KB_ROOT/knowledge/connections
$KB_ROOT/knowledge/sources
$KB_ROOT/knowledge/entities
$KB_ROOT/knowledge/qa
$KB_ROOT/reports
```

Drop `.gitkeep` files in the empty ones (`raw`, `daily`, `knowledge/connections`, `knowledge/sources`, `knowledge/entities`, `knowledge/qa`, `reports`).

On **fresh install only**, also create:

- `$KB_ROOT/knowledge/index.md` — seed it with:
  ```markdown
  # Knowledge Base Index

  | Article | Summary | Type | Updated |
  |---------|---------|------|---------|

  *(This index will populate as Claude Code captures conversations and you ingest documents.)*
  ```
- `$KB_ROOT/knowledge/log.md` — seed it with a header:
  ```markdown
  # Build Log

  Append-only log of compile and ingest operations.
  ```

### 5. Copy the runtime

Copy from `<skill-dir>/runtime/` into `$KB_ROOT/`:

```bash
cp -R <skill-dir>/runtime/scripts "$KB_ROOT/scripts"
cp -R <skill-dir>/runtime/hooks "$KB_ROOT/hooks"
cp <skill-dir>/runtime/pyproject.toml "$KB_ROOT/pyproject.toml"
cp <skill-dir>/runtime/AGENTS.md "$KB_ROOT/AGENTS.md"
```

Do not copy `uv.lock` — let `uv sync` regenerate it if needed. In upgrade mode, preserve `state.json` (it lives in `scripts/state.json` — copy it aside before the `scripts/` copy, then restore it).

### 6. Install Python dependencies

```bash
uv sync --directory "$KB_ROOT" --quiet
```

If this fails, report the error verbatim and stop.

### 7. Merge hooks into the project's settings.local.json

This is the step that makes auto-capture work. The hooks live at `$KB_ROOT/hooks/` and must be referenced with **absolute paths** via `uv run --directory $KB_ROOT`.

The target file is `<cwd>/.claude/settings.local.json` (create the `.claude/` directory if it does not exist).

Do **not** use `Write` to overwrite the file — it probably contains existing permissions that must be preserved. Instead, run a small Python merge script via Bash:

```bash
python3 - <<'PY'
import json, pathlib, shutil

settings_path = pathlib.Path("<cwd>/.claude/settings.local.json")
settings_path.parent.mkdir(parents=True, exist_ok=True)

if settings_path.exists():
    backup = settings_path.with_name(settings_path.name + ".bak-kb")
    if not backup.exists():
        shutil.copy(settings_path, backup)
    data = json.loads(settings_path.read_text())
else:
    data = {}

KB = "<absolute KB_ROOT>"
def cmd(hook_file):
    return f"uv run --directory {KB} python {KB}/hooks/{hook_file}"

hooks_block = {
    "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": cmd("session-start.py"), "timeout": 15}]}],
    "PreCompact":   [{"matcher": "", "hooks": [{"type": "command", "command": cmd("pre-compact.py"),   "timeout": 10}]}],
    "SessionEnd":   [{"matcher": "", "hooks": [{"type": "command", "command": cmd("session-end.py"),   "timeout": 10}]}],
}

existing = data.get("hooks") or {}
for k, v in hooks_block.items():
    existing[k] = v
data["hooks"] = existing

settings_path.write_text(json.dumps(data, indent=2) + "\n")
print("hooks wired:", list(data["hooks"].keys()))
PY
```

Substitute `<cwd>` and `<absolute KB_ROOT>` with real absolute paths before running.

If the file existed and had its own `hooks` section with entries we would clobber (for any of SessionStart / PreCompact / SessionEnd), **stop and ask the user** before overwriting. Do not silently replace existing hooks.

### 8. Smoke-test the hooks

Run the SessionStart hook against a fake stdin payload to confirm it responds with a JSON `hookSpecificOutput` block:

```bash
echo '{"session_id":"kb-setup-test","source":"startup","transcript_path":"/nonexistent"}' | \
  uv run --directory "$KB_ROOT" python "$KB_ROOT/hooks/session-start.py"
```

Expected: a one-line JSON object with `hookSpecificOutput.hookEventName == "SessionStart"`. If the exit code is non-zero or the output is empty, report the error and stop.

### 9. Report the result

Print a short summary:

```
Knowledge base ready at <KB_ROOT>
  Mode:         <fresh install | upgrade>
  Hooks:        wired into .claude/settings.local.json (backup: settings.local.json.bak-kb)
  Dependencies: installed via uv sync
  Smoke test:   session-start hook OK

Next steps:
  - Drop documents into <KB_ROOT>/raw/ then run /kb-ingest
  - Conversations will auto-capture from now on; compile with /kb-compile or wait for the 6pm auto-compile
  - Ask questions with /kb-query "your question"
  - Audit health with /kb-lint
```

## Upgrade safety rules

- **Never delete** `daily/`, `knowledge/`, `reports/`, or `state.json` contents.
- **Never overwrite** `.claude/settings.local.json` wholesale — only merge the three hook keys.
- **Always back up** the old settings file before writing (`settings.local.json.bak-kb`).
- **Preserve `knowledge/index.md` and `knowledge/log.md`** on upgrade. Only seed them if they do not exist.
