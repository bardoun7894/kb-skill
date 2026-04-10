---
name: kb-lint
description: Run health checks on the personal knowledge base to surface broken wikilinks, orphan pages, stale articles, missing backlinks, invalid frontmatter, and contradictions. Use before compiling, after large ingests, or when the user asks to audit the knowledge base.
allowed-tools: Bash Read
---

# kb-lint — audit the knowledge base

Thin wrapper around `scripts/lint.py`, which runs seven structural checks plus one optional LLM-based contradiction check.

## Prerequisites

The project must already be initialized by `/kb-setup`. If `ai-knowledge-base/scripts/lint.py` does not exist, ask the user to run `/kb-setup` first.

## The checks

1. **Broken links** — `[[wikilinks]]` that point to non-existent articles. Severity: error.
2. **Orphan pages** — articles that no other article links to. Severity: warning.
3. **Orphan sources** — daily logs that have not been compiled yet. Severity: warning.
4. **Stale articles** — daily logs that changed after compilation. Severity: warning.
5. **Frontmatter schema** — every article must have `name`, `description`, `type` (one of `concept`/`entity`/`source`/`connection`/`qa`), and live in the matching folder. Severity: error.
6. **Missing backlinks** — asymmetric links where A→B but not B→A. Severity: suggestion, auto-fixable.
7. **Sparse articles** — articles under 200 words. Severity: suggestion.
8. **Contradictions** (LLM, optional) — factual conflicts across articles. Severity: warning. Costs ~$0.15–$0.25.

## Steps

1. **Find the KB root.** Walk up from cwd to the first ancestor containing `scripts/lint.py`.

2. **Run the linter.** Default to `--structural-only` because it is free and instant:
   ```bash
   uv run --directory <kb-root> python scripts/lint.py --structural-only
   ```
   Only run the full version (without `--structural-only`) if the user explicitly asks for a contradiction check or agrees to the cost.

3. **Summarize the report.** The script writes `reports/lint-YYYY-MM-DD.md` and prints a one-line summary. Pass the summary through, then if there are **errors**, read the report file and list them with file paths so the user can jump to the source.

4. **Fix obvious issues if asked.** Auto-fixable suggestions (missing backlinks) can be applied with Edit by adding the reverse link to the target article's "See also" section. Do not touch structural errors without explicit user approval.
