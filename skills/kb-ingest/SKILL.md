---
name: kb-ingest
description: Manually ingest documents from raw/ into the personal knowledge base as structured, cross-linked wiki pages. Use when the user drops files into the knowledge base raw/ inbox and asks to ingest them, process them, or compile them into the wiki. This is the manual counterpart to the automatic conversation-capture flow.
allowed-tools: Bash Read Write Edit Glob Grep
---

# kb-ingest — manually ingest documents into the knowledge base

This skill turns arbitrary documents (web clips, PDFs converted to text, meeting notes, specs, research papers, transcripts) sitting in `ai-knowledge-base/raw/` into structured wiki pages under `ai-knowledge-base/knowledge/`. It is modeled on `NicholasSpisak/second-brain`'s `/second-brain-ingest` command, adapted to share the same knowledge tree as the automatic conversation-capture flow.

## Prerequisites

The project must already be initialized by `/kb-setup`. The KB must contain a `raw/` folder, a `knowledge/` folder with the subdirs `concepts/`, `connections/`, `sources/`, `entities/`, `qa/`, and a populated `knowledge/log.md`. If any of those are missing, ask the user to run `/kb-setup` first.

## Workflow

### 1. Locate the KB root

Walk up from the current working directory looking for a folder that contains both `raw/` and `knowledge/index.md`. Do not guess — confirm with `Glob` or `Bash`. Default location: `<project>/ai-knowledge-base/`. If nothing is found within five levels, stop and tell the user to run `/kb-setup`.

### 2. Find unprocessed files in raw/

List every file under `raw/**/*` (ignore `.gitkeep`, `.DS_Store`, `assets/`). Cross-reference against `knowledge/log.md` — any entry whose log line mentions the filename is already ingested. Skip it.

If there is nothing new to process, report that and stop.

### 3. Read and summarize each unprocessed file

For each new file, in order (smallest first so the user can warm up):

- Read the file in full with the Read tool. If it is a PDF, ask the user to convert it to text first — this skill does not shell out to PDF tools.
- Extract **3 to 5 key takeaways** in plain prose, no wikilinks yet. These should be *factual*, not interpretive.
- Surface any proper nouns (people, organizations, products, technologies) as candidate entities.
- Present the takeaways and candidate entities to the user in a compact block:

  ```
  Next up: raw/<filename>
  Key takeaways:
    1. …
    2. …
    3. …
  Candidate entities: <name>, <name>
  Candidate concepts: <topic>, <topic>
  Proceed? (y / n / skip)
  ```

- **Wait for confirmation.** Do not write any files until the user approves this specific document.

### 4. Write the source page (on approval)

Create `knowledge/sources/<slug>.md`. `<slug>` is a URL-safe lowercase-hyphen form of the filename's stem. Use this frontmatter exactly:

```yaml
---
name: <human title derived from the document>
description: <the one-line summary the user approved>
type: source
sources: [raw/<original-filename>]
created: <today YYYY-MM-DD>
updated: <today YYYY-MM-DD>
---
```

Body layout:

```markdown
# <title>

## Summary
<2–4 sentences summarizing the document as it actually says it — factual, no interpretation>

## Key points
- <bullet 1>
- <bullet 2>
- <bullet 3>

## Quotes
> <only if the document has quotable material worth preserving verbatim>

## See also
- <wikilinks to the entity and concept pages you are about to create or update>
```

**Important:** source pages are for facts, not opinions. Any interpretation, synthesis, or recommendation belongs in a concept page (step 5), not here.

### 5. Update or create entity pages

For each candidate entity, check whether `knowledge/entities/<slug>.md` already exists.

- **If it exists**, Read it, append the new fact(s) from this document to the relevant section, add `raw/<filename>` to the `sources:` list in its frontmatter, and bump `updated:` to today. Add a `[[sources/<slug>]]` wikilink in its "See also" section.
- **If it does not exist**, create it with this frontmatter:

  ```yaml
  ---
  name: <entity name>
  description: <one-line identification: who/what it is>
  type: entity
  sources: [sources/<source-slug>]
  created: <today>
  updated: <today>
  ---
  ```

  Body: a short "What it is" paragraph, a "Key facts" bullet list, and a "See also" section that links back to the source page and any related concepts.

### 6. Update or create concept pages

For each candidate concept:

- Prefer updating an existing `knowledge/concepts/<slug>.md` over creating a new one. Use `Grep` to find concepts whose `name:` or `description:` frontmatter matches the topic closely.
- When updating, append the new insight, cite the source via `[[sources/<slug>]]`, add the source path to `sources:`, and bump `updated:`.
- When creating new, use this frontmatter:

  ```yaml
  ---
  name: <concept name>
  description: <one-line summary of the idea>
  type: concept
  sources: [sources/<source-slug>]
  created: <today>
  updated: <today>
  ---
  ```

  Body: "# Title", then 2–4 paragraphs of neutral encyclopedia-style prose, then a "See also" section with at least two `[[...]]` wikilinks to related concepts, entities, or sources.

### 7. Cross-link everything

Use the `[[concepts/slug]]`, `[[entities/slug]]`, `[[sources/slug]]` wikilink form (with the folder prefix). Bare `[[slug]]` links will fail the linter. Every new page must have at least two outgoing wikilinks. Update existing "See also" sections to add reciprocal links so the missing-backlink check stays clean.

### 8. Update the index

Append one row per new article to `knowledge/index.md`:

```markdown
| [[sources/<slug>]] | <one-line description> | <type> | <YYYY-MM-DD> |
```

If the index has a different column layout, match whatever is already there.

### 9. Append to the log

Add an entry to `knowledge/log.md`:

```markdown
## [<ISO timestamp with timezone>] ingest | raw/<filename>
- Source: raw/<filename>
- Source page: [[sources/<slug>]]
- Concepts created: [[concepts/x]], [[concepts/y]]
- Concepts updated: [[concepts/z]] (if any)
- Entities created: [[entities/a]] (if any)
- Entities updated: [[entities/b]] (if any)
- Contradictions with existing articles: <list any, or "none">
```

### 10. Report back

Print a compact summary:

```
Ingested raw/<filename>
  Source page:    knowledge/sources/<slug>.md
  Concepts:       created N, updated M
  Entities:       created N, updated M
  Contradictions: <none | list>
```

Then ask whether to continue with the next unprocessed file, stop, or run `/kb-lint` to verify the changes.

## Rules and principles

- **Ask before writing.** Every document requires user approval after step 3. Do not batch-ingest silently.
- **Facts vs interpretation.** Source pages are factual. Interpretation, synthesis, and opinion go in concept pages.
- **Prefer updates over duplicates.** Search existing articles first. A duplicate concept page is worse than a stale one.
- **Wikilinks use folder prefixes.** Always `[[concepts/foo]]`, never `[[foo]]`.
- **One ingest per document.** Do not try to ingest multiple documents into the same source page.
- **Hands off conversation-only territory.** Do not touch `daily/` or create `connection/` pages from a single source — connections are synthesized by `/kb-compile` across multiple articles.
- **Expect 5–15 wiki pages touched per source.** Mostly updates, not creates.
- **Stop and ask** if you encounter a contradiction with an existing article, a document you do not understand well enough to summarize, or frontmatter that does not match the schema. Do not silently paper over it.
