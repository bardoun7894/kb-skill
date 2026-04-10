---
name: kb-publish
description: Publish the local knowledge base articles to a NotebookLM notebook so they can be queried from the NotebookLM web UI. Diffs new and changed articles against a local tracking file, uploads them via the notebooklm-mcp source_add tool, and deletes sources for articles that were removed locally. Use when the user asks to sync, publish, push, or upload the knowledge base to NotebookLM, or after running /kb-compile or /kb-ingest to mirror changes to the cloud.
allowed-tools: Bash Read Write Edit Glob
---

# kb-publish — mirror the knowledge base to NotebookLM

This skill keeps a NotebookLM notebook in sync with the local `knowledge/` tree. After running it, every concept, source, entity, connection, and qa article exists as a NotebookLM source, so the NotebookLM web UI becomes a queryable mirror of the KB that works from any device.

This skill only **pushes** local → NotebookLM. It never pulls changes back — if you want content authored in NotebookLM to land in the KB, export it to `raw/` manually and run `/kb-ingest`.

## Prerequisites

- The project must already be initialized by `/kb-setup` (the KB folder must exist).
- The `notebooklm-mcp` MCP server must be configured and authenticated. If any `mcp__notebooklm-mcp__*` tool returns an authentication error, stop and tell the user to run `nlm login` in their terminal.
- The project has, or is about to get, a notebook ID. This skill will prompt for one on first run and store it in `scripts/state.json` under `notebooklm.notebook_id`.

## Workflow

### 1. Locate the KB root

Walk up from the current working directory to the first ancestor containing `knowledge/index.md` and `scripts/state.json`. Default location: `<project>/ai-knowledge-base/`. If nothing is found, stop and tell the user to run `/kb-setup` first.

### 2. Resolve the notebook ID

Read `scripts/state.json`. If `state["notebooklm"]["notebook_id"]` exists, use it. Otherwise ask the user once:

> "Which NotebookLM notebook should I publish to? Paste the notebook ID (the UUID in the notebooklm.google.com URL, e.g. `f8502e21-e8a9-46a5-9a1f-bc7917912fec`)."

Store the answer in `state["notebooklm"]["notebook_id"]` and save state.json back. Also persist `state["notebooklm"]["sources"]` as an empty dict on first run — this is the mapping from `knowledge/<rel-path>.md` to the NotebookLM source ID that represents it.

### 3. Inventory local articles

List every article under these directories:

- `knowledge/concepts/`
- `knowledge/sources/`
- `knowledge/entities/`
- `knowledge/connections/`
- `knowledge/qa/`

For each article, compute a short content hash (the first 16 hex chars of the SHA-256 of its full file contents — use `python3 -c` or `shasum` via Bash). Key the inventory by the path **relative to `knowledge/`**, e.g. `concepts/architecture.md`.

Also read `knowledge/index.md` and treat it as a single extra article with the relative path `index.md` — it is the entry point a NotebookLM user should land on first.

### 4. Diff against the tracked state

Compare the fresh inventory against `state["notebooklm"]["sources"]`, which looks like:

```json
{
  "concepts/architecture.md": {
    "source_id": "abcdef12...",
    "hash": "be80189cabe73e56",
    "published_at": "2026-04-10T20:15:00+01:00"
  },
  ...
}
```

Produce four lists:

- **new** — local article not in the tracked state
- **changed** — local hash differs from tracked hash
- **unchanged** — local hash matches tracked hash (skip)
- **deleted** — tracked article no longer exists on disk

### 5. Show the plan and confirm

Present a compact summary to the user:

```
Publish plan for notebook <notebook_id>:
  New:       N articles
  Changed:   M articles
  Unchanged: K articles (skipped)
  Deleted:   D sources to remove

First 5 new:     concepts/foo.md, concepts/bar.md, ...
First 5 changed: entities/baz.md, ...
First 5 deleted: concepts/old.md, ...
```

Warn about the NotebookLM source-count ceiling (~300 sources per notebook) if `new + (existing - deleted)` would exceed 250. In that case, suggest the user either prune old articles or switch to a bundled mode (one source per folder instead of one per article — not yet implemented).

**Wait for explicit user confirmation** before any upload or delete.

### 6. Execute the plan

Process in this order so transient failures leave the state as clean as possible:

**a. Deletes first.** For each deleted entry, call `mcp__notebooklm-mcp__source_delete` with the tracked `source_id` and `confirm=True`. If it fails with "not found", treat as already deleted (remove from tracked state and continue). If it fails with another error, stop and report — do not proceed to uploads.

**b. Changed next.** For each changed entry, **delete** the old source (`source_delete` with the stored `source_id`), then upload the new content as a fresh source (see step c). This is because the NotebookLM MCP does not support in-place source updates.

**c. New uploads.** For each new or just-deleted-for-change article:

1. Read the article file in full with the Read tool.
2. Parse its YAML frontmatter to get the `name:` field. Fall back to the filename stem if frontmatter is missing.
3. Call:

   ```
   mcp__notebooklm-mcp__source_add(
     notebook_id=<notebook_id>,
     source_type="text",
     text=<full article markdown including frontmatter>,
     name="<rel-path> — <frontmatter name>"
   )
   ```

   The name is prefixed with the relative path so sources sort naturally in the NotebookLM sidebar and the user can tell at a glance which article a source corresponds to.

4. Capture the returned source ID from the tool result.
5. Update `state["notebooklm"]["sources"][rel_path]` with `{source_id, hash, published_at}`. Use the current ISO timestamp for `published_at`.

**After every 5 uploads**, save state.json to disk. This way if the skill is interrupted (network failure, tool timeout), the already-published articles are not re-uploaded on the next run.

### 7. Final state save

After the last upload or delete succeeds, persist the updated `state["notebooklm"]` block to `scripts/state.json` one more time. Then append an entry to `knowledge/log.md`:

```markdown
## [<ISO timestamp>] publish | notebooklm
- Notebook: <notebook_id>
- Uploaded: N new, M changed
- Deleted:  D sources
- Total published: <count of state["notebooklm"]["sources"]>
```

### 8. Report back

Print a compact summary:

```
Published to NotebookLM
  Notebook:        <notebook_id>
  Uploaded:        N new + M changed = (N+M) sources
  Deleted:         D sources
  Total in sync:   <count> sources
  View it at:      https://notebooklm.google.com/notebook/<notebook_id>
```

Then stop. Do not invoke any other skill.

## Rules and safety

- **One-way only.** This skill pushes local → NotebookLM. It does not read sources from NotebookLM to sync back down. If the user authored content directly in NotebookLM, it will not be touched.
- **Destructive deletes need confirmation.** Never delete a NotebookLM source without first showing it in the plan and getting user approval.
- **Never touch non-publish state.** Do not modify `state["ingested"]`, `state["query_count"]`, or any other state key — only `state["notebooklm"]`.
- **Preserve the mapping on failure.** If an upload fails partway through, the state already reflects the articles that did succeed. Re-running the skill should be idempotent — the hash comparison picks up exactly where the previous run left off.
- **Source-count ceiling.** NotebookLM caps notebooks at roughly 300 sources. Warn before exceeding 250 and ask the user what to do. A future bundled mode (one source per folder) can push this ceiling higher if needed.
- **Name collisions.** NotebookLM allows multiple sources with the same name. The `<rel-path>` prefix in the source name is what makes entries distinguishable, so do not drop it.
- **Do not publish empty articles.** If an article is fewer than 50 characters of non-frontmatter body, skip it and warn — it is almost certainly a scaffold the user has not filled in yet.

## Typical cost

Zero Claude Agent SDK cost (this skill does not call the LLM for extraction). The only cost is the time spent reading files and making MCP tool calls — usually 10–60 seconds for a full sync of a 50-article knowledge base.
