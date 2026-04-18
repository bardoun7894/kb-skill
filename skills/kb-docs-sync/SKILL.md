---
name: kb-docs-sync
description: Sync project docs (CLAUDE.md, README.md, docs/**/*.md, specs) into the KB as mirrored source pages. Creates pages for new docs, updates pages on source change, deletes pages whose source was removed. Use on "sync docs", "mirror documentation into the KB", "update the KB from project docs". Only touches pages with a `sync_origin` frontmatter marker — user-authored pages untouched.
allowed-tools: Bash Read Write Edit Glob Grep
---

# kb-docs-sync — mirror project docs into the knowledge base

This skill keeps a one-way mirror from tracked project documentation markdown files into the KB's `knowledge/sources/` folder. It is **not** a semantic extractor — it copies the document verbatim (plus a thin frontmatter header) so the doc becomes queryable through `/kb-query`, lintable through `/kb-lint`, and publishable through `/kb-publish`. If you want concept/entity extraction on top of the synced doc, run `/kb-ingest` on the same file afterwards.

## What gets synced

Project documentation files matching the configured glob patterns. Defaults:

- `CLAUDE.md`
- `README.md`
- `docs/**/*.md`
- `specs/**/*.md`
- `plans/**/*.md`

Paths are relative to the **project root** (the first ancestor of cwd that contains `.git/` or `.claude/`), not to the KB root. So `docs/api.md` means `<project>/docs/api.md`, and it ends up at `<project>/ai-knowledge-base/knowledge/sources/docs-api.md`.

The `ai-knowledge-base/` folder itself is always excluded from the sync — this skill never mirrors its own outputs.

## How identity works

Each synced source page carries a `sync_origin:` key in its frontmatter:

```yaml
---
name: docs/api.md
description: Auto-synced from docs/api.md
type: source
sync_origin: docs/api.md
sync_hash: be80189cabe73e56
created: 2026-04-10
updated: 2026-04-10
---
```

**The `sync_origin` key is the contract.** This skill only ever touches pages that have it set. Pages created by `/kb-ingest` or hand-written concept pages lack `sync_origin:` and are therefore invisible to `/kb-docs-sync`. You can delete stray synced pages safely by running `/kb-docs-sync` after removing the source file — it will detect the missing source and propose the deletion.

## Workflow

### 1. Locate the KB root and project root

Walk up from cwd to find:

- **KB root** — the first ancestor containing `knowledge/index.md` and `scripts/state.json`.
- **Project root** — the first ancestor containing `.git/` or `.claude/`. Usually the parent of the KB root, but not always — respect whatever the user set up.

If either is missing, stop and tell the user to run `/kb-setup` first.

### 2. Load or prompt for sync configuration

Read `scripts/state.json`. If `state["docs_sync"]["patterns"]` exists, use it. Otherwise:

1. Propose the default patterns listed above.
2. Show them to the user and ask:

   > "I'll sync these documentation patterns by default: `CLAUDE.md`, `README.md`, `docs/**/*.md`, `specs/**/*.md`, `plans/**/*.md`. Press enter to accept, or give me a comma-separated list of glob patterns."

3. Store the answer under `state["docs_sync"]["patterns"]` and persist state.json. Also initialize `state["docs_sync"]["files"]` as an empty dict on first run — this is the tracking map from project-relative path to `{slug, hash, synced_at}`.

### 3. Resolve the patterns to an actual file list

Use `Glob` or `Bash` (whichever is cleanest — `Glob` does not support brace expansion, so for `docs/**/*.md` you want `Glob` but for more exotic patterns fall back to Bash `find`). For each pattern, expand relative to the project root.

Filter out:

- Any path inside `ai-knowledge-base/` or `knowledge/` or `raw/` or `daily/` (the KB's own tree).
- Any path inside `.git/`, `node_modules/`, `.venv/`, or other generated trees.
- Files larger than 500 KB — they are almost certainly generated and do not belong in the KB.
- Files that have not been modified and whose content is shorter than 40 bytes (empty or nearly-empty stubs).

Deduplicate and sort the result for deterministic output.

### 4. Compute the diff

For each file in the fresh list, compute the short SHA-256 hash (first 16 hex chars) of its raw bytes. Compare against `state["docs_sync"]["files"]`:

- **new** — tracked state has no entry for this path.
- **changed** — tracked hash differs from current hash.
- **unchanged** — tracked hash matches current hash.

For each tracked entry whose path is **not** in the fresh list:

- **deleted** — tracked state has an entry but the source file is gone.

Only count as deleted if the corresponding source page still exists on disk — if the user already removed the page manually, treat it as already deleted (drop it from state without asking).

### 5. Show the plan and confirm

Present a compact summary:

```
docs-sync plan:
  New:       N files  → new source pages
  Changed:   M files  → source pages will be overwritten
  Deleted:   D files  → source pages will be removed
  Unchanged: K files  → skipped

First 5 new:
  - CLAUDE.md
  - docs/api.md
  - specs/001-booking-flow.md
  ...

First 5 changed:
  - README.md

First 5 deleted:
  - docs/old-rfc.md
```

**Wait for explicit user confirmation** before writing or deleting anything. If the plan is empty (zero new/changed/deleted), report "nothing to sync" and stop.

### 6. Execute the plan

Process in this order so partial failures are recoverable:

**a. Deletes first.** For each deleted entry:

1. Read the source page at `knowledge/sources/<slug>.md`.
2. Verify it has a `sync_origin:` key in its frontmatter that points back to the same project-relative path. If it does not, stop and warn — refuse to delete pages that aren't under sync control.
3. Delete the file with Bash (`rm`). Do not use Write to overwrite it with emptiness.
4. Remove the entry from `state["docs_sync"]["files"]`.

**b. Changed and new uploads.** For each new or changed file:

1. Read the source file in full.
2. Compute the target slug. Default rule: the project-relative path with `/` → `-` and `.md` stripped, lowercased. Examples:
   - `CLAUDE.md` → `claude-md`
   - `README.md` → `readme-md`
   - `docs/api.md` → `docs-api-md`
   - `specs/001-booking-flow.md` → `specs-001-booking-flow-md`
3. Target path: `knowledge/sources/<slug>.md`.
4. Build the new file contents as:

   ```markdown
   ---
   name: <project-relative path>
   description: Auto-synced from <project-relative path>
   type: source
   sync_origin: <project-relative path>
   sync_hash: <new-hash>
   created: <existing created: if this is an update, today if new>
   updated: <today>
   ---

   <!-- This page is auto-synced from <project-relative path> by /kb-docs-sync.
        Edits below this line will be overwritten on the next sync. Do not modify. -->

   <full verbatim contents of the source file>
   ```

   On **update**, preserve the `created:` value from the old page (read it first, re-use it). On **create**, use today's date.

5. Write the file. If the target path already exists and has a `sync_origin:` that does **not** match (or has no `sync_origin:` at all), stop and warn — do not clobber a user-authored page with a similar slug.

6. Update `state["docs_sync"]["files"][<project-relative path>]` with:

   ```json
   {
     "slug": "<slug>",
     "hash": "<new-hash>",
     "synced_at": "<ISO timestamp>"
   }
   ```

7. Every 10 files, save state.json to disk so an interrupted run is recoverable.

### 7. Append to the log

Once the plan finishes, append an entry to `knowledge/log.md`:

```markdown
## [<ISO timestamp>] docs-sync
- New:      N → [[sources/slug-1]], [[sources/slug-2]], ...
- Updated:  M → [[sources/slug-3]], ...
- Deleted:  D → slug-4, slug-5
- Patterns: CLAUDE.md, README.md, docs/**/*.md, specs/**/*.md, plans/**/*.md
```

### 8. Final state save

Persist `state["docs_sync"]` to `scripts/state.json` one last time.

### 9. Report back

```
docs-sync complete
  New:       N
  Updated:   M
  Deleted:   D
  Total tracked: <count of state["docs_sync"]["files"]>

Next steps:
  - Run /kb-lint to verify the sync produced clean frontmatter and no broken links
  - Run /kb-publish to push the updated source pages to NotebookLM (optional)
  - Run /kb-ingest on any interesting new source if you want concept/entity extraction
```

Then stop.

## Rules and safety

- **One-way mirror.** This skill only writes from project → KB. It never reads KB edits back into the project.
- **`sync_origin` is the only contract.** Pages without this key are invisible to the skill. You can hand-edit concepts, entities, or non-synced source pages without worrying about `/kb-docs-sync` touching them.
- **Never clobber user pages.** If a slug collides with an existing page that lacks `sync_origin:` or has a different `sync_origin:`, stop and ask the user — do not overwrite.
- **Always confirm before writing or deleting.** Step 5 is non-negotiable.
- **Exclude the KB from itself.** Files under `ai-knowledge-base/` (or whatever the KB folder is called) must never be selected for sync.
- **Size cap.** Skip anything over 500 KB. If a real doc exceeds that, it probably needs to be split first.
- **Hash-based diffing.** Don't rely on mtime — it's unreliable across git checkouts.
- **Re-runnable.** The entire flow must be idempotent. Running `/kb-docs-sync` twice in a row with no changes in between should produce "nothing to sync".

## Typical cost

Zero Claude Agent SDK cost. The skill does not call the LLM for extraction — it just reads and writes files. Runtime is usually a few seconds for a project with 10–50 tracked docs.
