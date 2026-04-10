---
name: kb-spec
description: Bridge between GitHub Spec Kit and the kb-* knowledge base. Queries the KB for prior art before each Spec Kit phase (specify, plan, tasks, implement) and writes the results into the feature's research.md as clearly labeled sections. After the feature is finalized, delegates to kb-docs-sync to mirror specs/**/*.md and plans/**/*.md into the KB. TRIGGER PROACTIVELY at the start of any Spec Kit phase — before running /speckit.specify run `/kb-spec pre` silently, before /speckit.plan run `/kb-spec plan`, before /speckit.tasks run `/kb-spec tasks`, before /speckit.implement run `/kb-spec implement`, and after the feature is finalized run `/kb-spec post`. Do not wait for the user to invoke kb-spec explicitly — it is a standing bridge between Spec Kit and the KB. Also use when the user says "new spec", "run speckit with KB context", or "sync the spec into KB".
allowed-tools: Bash Read Write Edit Glob Grep
---

# kb-spec — make Spec Kit and the KB fit each other

This skill is a thin bridge. It does **not** replace `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement`, or any kb-* skill — it wires them together so each Spec Kit phase sees prior decisions from the KB before it runs, and so every finalized feature flows back into the KB afterwards.

## Modes

Five modes, selected by the first positional argument. Each pre-phase mode writes into `specs/<NNN-short-name>/research.md` under a clearly labeled section — no Spec Kit file is overwritten, only `research.md` is touched.

| Mode        | When to run                     | KB query framing                                                                  | Output section in `research.md`       |
|-------------|---------------------------------|-----------------------------------------------------------------------------------|---------------------------------------|
| `pre`       | Before `/speckit.specify`       | "Prior decisions, constraints, or related work about `<feature area>`"            | `## Prior art from KB`                |
| `plan`      | Before `/speckit.plan`          | "Architectural decisions, tech stack choices, integration patterns for `<area>`"  | `## Architecture notes from KB`       |
| `tasks`     | Before `/speckit.tasks`         | "Task breakdown patterns, known pitfalls, testing approaches for `<area>`"        | `## Task patterns from KB`            |
| `implement` | Before `/speckit.implement`     | "Code patterns, conventions, bug fixes, gotchas about `<area>`"                   | `## Implementation notes from KB`     |
| `post`      | After `/speckit.tasks` finishes | N/A — delegates to `/kb-docs-sync` to mirror specs/**/*.md and plans/**/*.md      | (writes KB `knowledge/sources/` pages)|

Multiple pre-phase modes can run sequentially over the life of a feature. Each one replaces **only** its own section in `research.md` and leaves the other sections untouched.

If the user invokes the skill with no mode, pick based on the state of the current feature directory:

- No `spec.md` → **pre**
- `spec.md` exists, no `plan.md` → **plan**
- `plan.md` exists, no `tasks.md` → **tasks**
- `tasks.md` exists, no implementation progress detected → **implement**
- `tasks.md` exists and looks finalized → **post**

Ambiguous cases: ask the user which mode they want.

## Prerequisites

1. **Spec Kit installed.** Look for `.specify/templates/spec-template.md` under the project root or under `/Users/mohamedbardouni/.specify/`. If neither exists, stop and tell the user to install Spec Kit first.
2. **KB initialized.** Walk up from cwd to find `ai-knowledge-base/scripts/query.py` and `ai-knowledge-base/knowledge/index.md`. If missing, tell the user to run `/kb-setup`.
3. **kb-docs-sync available** (post mode only). Confirm `~/.agents/skills/kb-docs-sync/SKILL.md` exists — otherwise fall back to reporting the sync step as a manual follow-up.

## Shared workflow — pre-phase modes (`pre`, `plan`, `tasks`, `implement`)

All four pre-phase modes share the same skeleton. The only things that vary per mode are the **query framing** (column 3 in the table above) and the **output section heading** (column 4).

### 1. Resolve the feature directory

Mimic `common.sh::get_current_branch` from Spec Kit so the skill sees the same feature Spec Kit would:

```bash
# 1. $SPECIFY_FEATURE wins if set
# 2. git rev-parse --abbrev-ref HEAD if it looks like NNN-short-name
# 3. otherwise: highest NNN-* under specs/ at project root
```

Let `FEATURE_DIR = <project-root>/specs/<NNN-short-name>`. Create it if missing (idempotent with Spec Kit's own `create-new-feature.sh`).

### 2. Derive the KB query

The feature description comes from either:

- The skill arguments after the mode name (e.g. `/kb-spec plan "stripe webhook handling"`).
- Failing that, the first 400 bytes of `spec.md` if it exists.
- Failing that: for `plan`, read `spec.md` in full; for `tasks`, read `spec.md` + `plan.md`; for `implement`, read `spec.md` + `plan.md` + `tasks.md`.

Collapse the source material into **one** English question using the mode-specific framing from the table:

- **pre** → "What prior decisions, constraints, or related work does the KB have about `<key concept>`?"
- **plan** → "What architectural decisions, tech stack choices, or integration patterns does the KB document for `<key concept>`?"
- **tasks** → "What task breakdown patterns, known pitfalls, or testing approaches does the KB record for `<key concept>`?"
- **implement** → "What code patterns, conventions, bug fixes, or gotchas does the KB document about `<key concept>`?"

Keep it to one question per invocation. kb-query loads the full KB into context regardless, so one well-framed question surfaces the right articles as well as N scattered ones.

### 3. Run kb-query

```bash
uv run --directory <kb-root> python scripts/query.py "<derived question>"
```

Capture stdout verbatim. Do **not** pass `--file-back` — pre-phase modes are read-only against the KB. The feature's own spec/plan/tasks files will become KB source pages later when post mode runs, so writing a qa/ page now would duplicate.

### 4. Write or update `FEATURE_DIR/research.md`

If the file does not exist, create it with this skeleton:

```markdown
# Research: <feature short-name>

**Generated**: <ISO date>
**Feature**: [spec.md](./spec.md)

<!-- Sections below are populated by /kb-spec <mode> before each Spec Kit phase.
     Each section is owned by exactly one mode and is replaced wholesale on re-run.
     Free-form notes added by the user between sections are preserved. -->
```

Then ensure the mode's section heading exists and replace **only** the contents of that one section. Section headings, in the canonical order they appear in `research.md`:

1. `## Prior art from KB`           ← owned by `pre`
2. `## Architecture notes from KB`  ← owned by `plan`
3. `## Task patterns from KB`       ← owned by `tasks`
4. `## Implementation notes from KB`← owned by `implement`

Algorithm for section replacement:

- If the section does not yet exist: append it at the end of the file, preserving the canonical order above (i.e. insert it before any later-owned section that already exists).
- If the section already exists: replace everything from its `## ` heading up to (but not including) the next `## ` heading or EOF.
- Do not touch any other `##` section — user-authored notes between KB sections must survive.

Each KB section body should look like:

```markdown
## <section heading>

*Queried at <ISO timestamp> · Mode: <mode> · Question: "<derived question>"*

<kb-query output verbatim, including [[wikilinks]]>
```

Preserve the `[[wikilinks]]` — do not rewrite them to Markdown links.

### 5. Report back

Print a mode-specific summary:

```
kb-spec <mode> complete
  Feature:    <NNN-short-name>
  KB query:   "<question>"
  Citations:  [[sources/…]], [[concepts/…]], …
  Updated:    specs/<NNN-short-name>/research.md
              section: ## <section heading>

Next: run /speckit.<matching-phase> "<feature description>"
```

Then stop. Pre-phase modes are informational — they **never** invoke `/speckit.*` themselves. The user runs the matching Spec Kit phase manually (or via their own automation) so kb-spec stays decoupled from Spec Kit's command surface.

## Workflow — post mode

### 1. Resolve the feature directory (same as step 1 above)

If no feature can be resolved, fall back to a project-wide sync — the user may be cleaning up old specs rather than pushing a specific one.

### 2. Sanity-check the feature is finalized

A feature is considered finalized when `spec.md`, `plan.md`, and `tasks.md` all exist. If any is missing, warn:

> "Feature <NNN-short-name> is missing `<file>` — syncing now will mirror an incomplete feature. Continue?"

and wait for explicit yes.

### 3. Delegate to kb-docs-sync

Post mode does **not** reimplement mirroring. It invokes `/kb-docs-sync` as a subroutine:

- If the skill can call sibling skills directly, do so (`Skill: kb-docs-sync`).
- Otherwise, print a one-line instruction for the user: `"Run /kb-docs-sync now to mirror specs/**/*.md into the KB."` — this keeps kb-spec dependency-free.

kb-docs-sync's default patterns already include `specs/**/*.md` and `plans/**/*.md`, so no configuration is needed on first run. The sync will:

- Create `knowledge/sources/specs-<NNN-short-name>-spec-md.md` (and `-plan-md.md`, `-tasks-md.md`, `-research-md.md`) with the `sync_origin` frontmatter contract.
- Track hashes in `scripts/state.json` so re-running is idempotent.
- Append a `docs-sync` entry to `knowledge/log.md`.

### 4. Optional: conceptualize the feature

If the user explicitly asks for concept extraction (e.g. "also ingest it"), and only then, run `/kb-ingest` over the mirrored source pages. Default is mirror-only — kb-ingest costs LLM calls and requires per-file confirmation, which is overkill for the routine case.

### 5. Report back

```
kb-spec post complete
  Feature:    <NNN-short-name>
  Mirrored:   spec.md, plan.md, tasks.md, research.md  (via /kb-docs-sync)
  KB sources: [[sources/specs-<NNN>-spec-md]], [[sources/specs-<NNN>-plan-md]], …

Next:
  - Run /kb-lint to verify the sync
  - Run /kb-publish to push to NotebookLM
  - Run /kb-query to ask questions about this feature or related ones
```

## Rules and safety

- **Never invoke `/speckit.*` automatically.** kb-spec only informs the human; it does not chain the Spec Kit workflows. This keeps the two toolchains decoupled so a break in one doesn't cascade.
- **Never mirror before a feature is finalized** without explicit user confirmation. Draft specs leak half-decisions into the KB and pollute future queries.
- **Reuse, don't reimplement.** Mirroring goes through kb-docs-sync. Querying goes through kb-query. If either skill changes its interface, kb-spec breaks loudly rather than silently drifting.
- **One-way only, like kb-docs-sync.** KB → spec never happens. The only writes into spec dirs are the phase-specific KB sections inside `research.md`.
- **Canonical section ownership.** Each `## … from KB` section is owned by exactly one mode. Re-running a mode replaces only its own section. User-authored sections between KB sections must survive.
- **Respect Spec Kit's feature resolution.** Use the same $SPECIFY_FEATURE → git branch → highest NNN precedence so kb-spec and Spec Kit always agree on "the current feature".
- **Idempotent.** Re-running any pre-phase mode replaces only its section in `research.md`. Re-running post mode is a no-op if no spec files changed (kb-docs-sync handles this via hashes).

## Typical cost

- **Each pre-phase mode** (`pre`, `plan`, `tasks`, `implement`): one kb-query call ≈ $0.15–$0.25. Over a full feature that's 4 calls ≈ $0.60–$1.00.
- **Post mode**: zero LLM cost (kb-docs-sync is pure file I/O).

If cost matters, run only `pre` + `post` (the bare minimum — prior art seeding + feedback loop) and skip `plan` / `tasks` / `implement` unless the feature is in an area with a lot of accumulated KB history.
