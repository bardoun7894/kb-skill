# kb-skill

A Claude Code skill pack that turns your work into a searchable personal knowledge base. Two paths feed one Obsidian-friendly vault:

- **Automatic** — Claude Code `SessionEnd` / `PreCompact` hooks capture your conversations into `daily/` logs. A Python compiler powered by the Claude Agent SDK turns those logs into structured concept and connection articles under `knowledge/`.
- **Manual** — you drop documents (web clips, meeting notes, specs, papers) into `raw/` and the `/kb-ingest` slash command compiles them into source and entity pages that share the same vault.

Both paths write into the same `knowledge/` tree, so a concept derived from a conversation and one derived from a paper are peers — the compiler and the ingester will update existing pages instead of creating duplicates.

Inspired by Andrej Karpathy's LLM Wiki pattern, the [claude-memory-compiler](https://github.com/coleam00/claude-memory-compiler) project, and [NicholasSpisak/second-brain](https://github.com/NicholasSpisak/second-brain).

## Slash commands

| Command | What it does |
|---|---|
| `/kb-setup` | Install the runtime + wire hooks into a project's `.claude/settings.local.json` |
| `/kb-ingest` | Manually ingest documents from `raw/` into `knowledge/sources/` + related pages |
| `/kb-docs-sync` | Mirror tracked project docs (CLAUDE.md, README.md, docs/**/*.md) into `knowledge/sources/`, updating on change and removing stale pages |
| `/kb-compile` | Compile new daily conversation logs into concept articles |
| `/kb-query` | Ask questions against the knowledge base with index-guided retrieval |
| `/kb-lint` | Run health checks (broken links, orphans, frontmatter, contradictions) |
| `/kb-publish` | Mirror the knowledge base to a NotebookLM notebook via the notebooklm-mcp server |
| `/kb-spec` | Bridge GitHub Spec Kit with the KB: query prior art into each feature's `research.md` before `/speckit.{specify,plan,tasks,implement}`, then delegate to `/kb-docs-sync` to mirror finalized specs back into the KB |

## Install

One-liner (recommended):

```bash
curl -fsSL https://raw.githubusercontent.com/bardoun7894/kb-skill/main/bootstrap.sh | bash
```

That clones the repo to `~/.local/share/kb-skill` and copies the eight `kb-*` skills into `~/.claude/skills/`, where Claude Code discovers them automatically. Re-run the same command any time to update.

Manual install (if you prefer to inspect before running):

```bash
git clone https://github.com/bardoun7894/kb-skill ~/.local/share/kb-skill
~/.local/share/kb-skill/install.sh
```

See [SETUP.md](SETUP.md) for details.

Then, in any project where you want a knowledge base:

```
/kb-setup
```

That's it. Conversations in that project will now auto-capture into `ai-knowledge-base/daily/` and compile into `knowledge/` after 6pm (or on demand via `/kb-compile`). Drop documents into `raw/` and run `/kb-ingest` to add them manually.

## Folder layout

```
<project>/
├── .claude/settings.local.json        # hooks merged in by /kb-setup
└── ai-knowledge-base/
    ├── raw/                            # manual document inbox
    ├── daily/                          # auto-captured conversation logs
    ├── knowledge/                      # the Obsidian vault target
    │   ├── index.md
    │   ├── log.md
    │   ├── concepts/                   # auto + manual (the merge point)
    │   ├── connections/                # cross-article synthesis
    │   ├── sources/                    # manual — per-document summaries
    │   ├── entities/                   # manual — people, orgs, products
    │   └── qa/                         # /kb-query --file-back
    ├── reports/                        # lint reports
    ├── scripts/, hooks/, pyproject.toml, AGENTS.md
    └── state.json
```

## Unified frontmatter schema

Every article under `knowledge/` uses:

```yaml
---
name: Human-readable title
description: One-line summary for the index
type: concept | entity | source | connection | qa
sources: [daily/2026-04-10.md, raw/spec.pdf]   # optional, list of source paths
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

`/kb-lint` validates this schema and complains if an article is missing required keys or lives in the wrong folder for its `type`.

## Requirements

- [uv](https://github.com/astral-sh/uv) for the Python runtime
- Claude Code with hook support
- An Anthropic subscription — the Claude Agent SDK runs under the subscription, no separate API credits needed

## Costs

Rough per-operation costs from the Claude Agent SDK:

| Operation | Cost |
|---|---|
| Session flush (hook → daily log) | $0.02 – $0.05 |
| `/kb-compile` per daily log | $0.45 – $0.65 |
| `/kb-query` | $0.15 – $0.25 |
| `/kb-query --file-back` | $0.25 – $0.40 |
| `/kb-lint` (structural only) | free |
| `/kb-lint` (with contradictions) | $0.15 – $0.25 |
| `/kb-ingest` | varies with document size, typically $0.10 – $0.50 |

## License

MIT.
