---
name: kb-query
description: Answer questions from the personal KB (auto-captured sessions + manually ingested docs). Trigger proactively before any question about project history, prior decisions, existing architecture, past bugs, "how did we do X before". Also trigger when the user starts describing a feature in a KB-known area so the answer is grounded in prior art. Returns a cited answer with [[wikilinks]] — read the citations before replying. Matches "what did we decide about X", "how did we fix Y", "what do we know about Z".
allowed-tools: Bash Read
---

# kb-query — ask the knowledge base a question

Thin wrapper around `scripts/query.py`, which does index-guided retrieval over the compiled `knowledge/` tree (concepts, connections, sources, entities, qa).

## Prerequisites

The project must already be initialized by `/kb-setup`. If `ai-knowledge-base/scripts/query.py` does not exist, ask the user to run `/kb-setup` first.

## Steps

1. **Find the KB root.** Walk up from cwd to the first ancestor containing `scripts/query.py` and `knowledge/index.md`. Default location: `<project>/ai-knowledge-base/`.

2. **Pass the question through.** Run:
   ```bash
   uv run --directory <kb-root> python scripts/query.py "<user question>"
   ```
   Quote the question so spaces do not confuse the shell. Print the script's answer verbatim.

3. **Offer file-back.** If the user's question is substantive and a clean answer came out, ask whether they want the answer persisted into `knowledge/qa/`. On approval, re-run with `--file-back`:
   ```bash
   uv run --directory <kb-root> python scripts/query.py "<user question>" --file-back
   ```
   This costs slightly more but creates a new Q&A article cross-linked into the index.

## Notes

- The query engine reads the **entire** knowledge base into the LLM's context. This is fine at personal scale (50–500 articles) and cheaper than standing up a vector database.
- Cost per query is roughly $0.15–$0.25 without `--file-back`, $0.25–$0.40 with it.
- The answer will cite specific articles via `[[wikilinks]]`. Do not rewrite or summarize those citations — pass them through so the user can navigate to the source.
