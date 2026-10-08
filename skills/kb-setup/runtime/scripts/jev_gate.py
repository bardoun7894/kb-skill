"""Jev article pre-selection gate for query.py.

`read_all_wiki_content()` puts every article body in the prompt. On a mature KB that is
~100 articles / ~270KB / ~67k tokens per query, and it only grows.

This asks Jev one `noul` per article over the *index rows only* — title plus one-line
summary, well inside the 32k state cap — and returns the subset worth loading in full.

Design rules:
  - Jev gates, the LLM writes. Nothing here generates text.
  - Jev never sees article bodies, only summaries.
  - Fail open. Any error, missing key, or oversized batch returns None, and the caller
    keeps the load-everything behaviour. A silent recall failure is worse than the
    tokens it saves: the LLM says "not in the KB" and the user believes it.

CLI, so every surface shares one implementation (Claude, pi, opencode, codex, gemini,
hooks, cron) instead of re-deriving the judgement from prose in a skill file:

    python3 jev_gate.py "how did we deploy the site"     # ids, one per line
    python3 jev_gate.py --json --explain "<question>"    # machine-readable

Exit 0 selection made · 1 fell open (load everything) · 2 no key.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import jev
from config import KNOWLEDGE_DIR
from utils import list_wiki_articles, parse_frontmatter, read_wiki_index

LOG_TAG = "kb-query"

# One question per article makes this a far wider request than a single decision, and a
# timeout here means falling back to sending the whole KB — the thing we are avoiding.
TIMEOUT = float(os.environ.get("KB_QUERY_JEV_TIMEOUT", "20"))

# Deliberately low: the gate is biased toward over-including. Dropping the one article
# that held the answer is invisible to the user; loading one extra is not.
#
# 0.20 was measured against full-KB ground truth over 3 questions / 17 cited articles
# (2026-09-21): it matches the old fat-payload gate's 82% recall while keeping fewer
# articles. Drop to 0.12 for 100% recall on that sample, at the cost of keeping ~60% of
# the KB — worth it if you would rather pay tokens than ever miss an article.
THRESHOLD = float(os.environ.get("KB_QUERY_JEV_THRESHOLD", "0.20"))

# ~100 questions in one request is proven; above this there is no evidence, so fail open.
MAX_ARTICLES = int(os.environ.get("KB_QUERY_JEV_MAX_ARTICLES", "150"))

# Below these, loading the whole KB is already cheap and the gate can only lose recall.
MIN_ARTICLES = int(os.environ.get("KB_QUERY_JEV_MIN_ARTICLES", "25"))
MIN_BYTES = int(os.environ.get("KB_QUERY_JEV_MIN_BYTES", "60000"))

# A question this short carries too little signal to filter ~100 summaries against.
MIN_QUESTION_CHARS = int(os.environ.get("KB_QUERY_JEV_MIN_QUESTION_CHARS", "12"))

# Below this, an empty selection is trusted as "the KB genuinely has nothing on this"
# rather than read as a gate misfire. Only reached when nothing cleared THRESHOLD.
NOTHING_HERE = float(os.environ.get("KB_QUERY_JEV_NOTHING_HERE", "0.35"))

# ── Link expansion ─────────────────────────────────────────────────────
# The KB carries ~6 [[wikilinks]] per article — 575 edges that retrieval ignored
# entirely. Measured 2026-09-21: both articles the gate missed on a Tailscale question
# were directly linked from articles it had already selected. Walking one hop out from
# the confident hits recovers them for ZERO extra Jev cost, because it is pure graph
# traversal — no second request.
#
# Expansion runs only from *strong* hits. Expanding from every marginal hit pulls in the
# world: an article scraping past THRESHOLD is exactly the one whose neighbours are noise.
EXPAND = os.environ.get("KB_QUERY_JEV_EXPAND", "1") != "0"
EXPAND_FROM = float(os.environ.get("KB_QUERY_JEV_EXPAND_FROM", "0.60"))

# Never let expansion swallow the KB — past this share, the prompt saving is gone and
# we are better off admitting the gate had no opinion.
EXPAND_MAX_SHARE = float(os.environ.get("KB_QUERY_JEV_EXPAND_MAX_SHARE", "0.60"))

# The rubric travels ONCE, inside the state; each question carries only its article id.
# The obvious alternative — repeating the rubric in every question's `instructions` —
# cost 66% of the whole request: 96 copies of a 504-char paragraph, 17,121 input tokens
# against 7,389 for this shape. Measured 2026-09-21: same recall, 57% cheaper, ~40%
# faster. Lengthening this rubric is O(1); never move it back to per-question.
RUBRIC = (
    "For each question below you are given one article id from the `articles` list in "
    "the state. Answer whether that article is worth reading in full to answer "
    "`question`. Say yes when the article plausibly touches the question's subject, "
    "system, or symptom — a partial or background match counts. Say no only when it is "
    "clearly about something else. The one-line summary is all you can see; a vague "
    "summary is not evidence of irrelevance."
)

# Asked speculatively in the same request — same state, same latency, no extra round trip.
KB_RELEVANT_INSTRUCTIONS = (
    "Looking only at the list of article summaries in the state, does this knowledge base "
    "plausibly contain anything that would help answer the question? Say yes if any article "
    "touches the same system, project, tool, or problem, even loosely. Say no only when the "
    "question is about something the KB has clearly never covered."
)


# ── Catalog ────────────────────────────────────────────────────────────

INDEX_ROW = re.compile(r"^\|\s*\[\[([^\]]+)\]\]\s*\|\s*([^|]*)\|")


def index_summaries() -> dict[str, str]:
    """Map article id -> one-line summary, parsed from knowledge/index.md rows."""
    summaries: dict[str, str] = {}
    for line in read_wiki_index().splitlines():
        m = INDEX_ROW.match(line.strip())
        if m:
            summaries[m.group(1).strip()] = m.group(2).strip()
    return summaries


def _fallback_summary(path: Path) -> str:
    """Summary for an article the index does not list: frontmatter, then first prose line."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    fm = parse_frontmatter(content) or {}
    desc = fm.get("description") or fm.get("name")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    body = content.split("---", 2)[-1]
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line[:200]
    return ""


def build_catalog() -> list[dict[str, str]]:
    """Every article on disk, with the best one-line summary available for it."""
    summaries = index_summaries()
    catalog = []
    for path in list_wiki_articles():
        article_id = path.relative_to(KNOWLEDGE_DIR).with_suffix("").as_posix()
        catalog.append({
            "id": article_id,
            "summary": summaries.get(article_id) or _fallback_summary(path),
        })
    return catalog


WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")


def build_link_graph() -> dict[str, set[str]]:
    """article id -> the article ids it links to. Dangling links are dropped."""
    raw: dict[str, set[str]] = {}
    for path in list_wiki_articles():
        article_id = path.relative_to(KNOWLEDGE_DIR).with_suffix("").as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            content = ""
        raw[article_id] = set(WIKILINK.findall(content))
    known = set(raw)
    return {a: (links & known) for a, links in raw.items()}


def expand_by_links(
    selected: set[str],
    strong: set[str],
    graph: dict[str, set[str]] | None = None,
    max_share: float = EXPAND_MAX_SHARE,
) -> set[str]:
    """Add the 1-hop neighbours of the confident hits. Free — no extra Jev call.

    `strong` is the subset of `selected` that scored above EXPAND_FROM; only those are
    expanded from. Returns `selected` unchanged if expansion would swallow more than
    `max_share` of the KB.
    """
    if not EXPAND or not strong:
        return selected
    graph = build_link_graph() if graph is None else graph
    if not graph:
        return selected

    expanded = set(selected)
    for article_id in strong:
        expanded |= graph.get(article_id, set())

    if len(expanded) > max_share * len(graph):
        return selected
    return expanded


def corpus_bytes() -> int:
    """Total size of all article bodies — what the gate is trying to avoid sending."""
    total = 0
    for path in list_wiki_articles():
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


# ── When the gate applies ──────────────────────────────────────────────

def gate_applies(question: str, catalog: list[dict[str, str]] | None = None) -> tuple[bool, str]:
    """Whether it is worth spending a Jev call on this query at all.

    All deterministic and free — no API call. Returns (applies, reason); the reason is
    printed so a skipped gate is never a mystery.
    """
    if os.environ.get("KB_QUERY_JEV_GATE", "1") == "0":
        return False, "gate disabled (KB_QUERY_JEV_GATE=0)"
    if len((question or "").strip()) < MIN_QUESTION_CHARS:
        return False, f"question under {MIN_QUESTION_CHARS} chars — too little signal to filter on"

    catalog = build_catalog() if catalog is None else catalog
    if not catalog:
        return False, "no articles"
    if len(catalog) < MIN_ARTICLES:
        return False, f"only {len(catalog)} articles — whole KB is already cheap"
    if len(catalog) > MAX_ARTICLES:
        return False, f"{len(catalog)} articles exceeds batch cap {MAX_ARTICLES}"

    total = corpus_bytes()
    if total < MIN_BYTES:
        return False, f"corpus is {total:,}B, under the {MIN_BYTES:,}B budget"
    if not (jev.typesafe_key() or jev.api_key()):
        return False, "no API key in env, <kb-root>/.env, ~/.env or opencode auth.json"
    return True, f"{len(catalog)} articles / {total:,}B"


# ── The gate ───────────────────────────────────────────────────────────

def select_articles(
    question: str,
    catalog: list[dict[str, str]] | None = None,
    threshold: float = THRESHOLD,
) -> tuple[set[str] | None, float | None]:
    """(article ids worth loading in full, kb_relevant probability).

    The first element is None to mean "fall back to loading everything" — returned for
    every failure mode: gate not applicable, no key, HTTP error, timeout, malformed
    response, empty or oversized catalog.

    The second is Jev's speculative read on whether the KB holds anything at all for this
    question (None when unknown). It rides the same request at no extra latency.
    """
    catalog = build_catalog() if catalog is None else catalog
    applies, _reason = gate_applies(question, catalog)
    if not applies:
        return None, None

    keys = [f"a{i}" for i in range(len(catalog))]
    state = {"question": question, "task": RUBRIC, "articles": catalog}
    questions = {
        k: {"type": "noul", "instructions": art["id"]} for k, art in zip(keys, catalog)
    }
    questions["kb_relevant"] = {"type": "noul", "instructions": KB_RELEVANT_INSTRUCTIONS}

    answers = jev.ask(state, questions, tag=LOG_TAG, timeout=TIMEOUT)
    if not answers:
        return None, None

    relevant = answers.get("kb_relevant")
    kb_relevant = relevant.get("noul") if isinstance(relevant, dict) else None
    if not isinstance(kb_relevant, (int, float)):
        kb_relevant = None

    selected = set()
    strong = set()
    for k, art in zip(keys, catalog):
        answer = answers.get(k)
        if not isinstance(answer, dict):
            # A missing answer is not a "no" — include the article.
            selected.add(art["id"])
            continue
        noul = answer.get("noul")
        if not isinstance(noul, (int, float)):
            selected.add(art["id"])
            continue
        if noul >= threshold:
            selected.add(art["id"])
            if noul >= EXPAND_FROM:
                strong.add(art["id"])

    if selected:
        selected = expand_by_links(selected, strong)

    if not selected:
        # Two very different situations produce an empty selection. If Jev also says the
        # KB holds nothing on this subject, believe it: send the index alone so the LLM
        # can answer "not in the KB" from summaries. Otherwise the gate misread the
        # question — fall open.
        if kb_relevant is not None and kb_relevant < NOTHING_HERE:
            return set(), kb_relevant
        return None, kb_relevant

    return selected, kb_relevant


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--json", action="store_true", help="emit a JSON object")
    parser.add_argument("--explain", action="store_true", help="print the gate's reasoning")
    args = parser.parse_args()

    cat = build_catalog()
    applies, reason = gate_applies(args.question, cat)
    if args.explain:
        print(f"applies={applies} reason={reason} articles={len(cat)} "
              f"corpus={corpus_bytes():,}B", file=sys.stderr)

    if not applies and not (jev.typesafe_key() or jev.api_key()):
        print(f"jev gate unavailable: {reason}", file=sys.stderr)
        return 2

    selected, kb_relevant = select_articles(args.question, cat)

    if args.json:
        print(json.dumps({
            "applies": applies,
            "reason": reason,
            "selected": sorted(selected) if selected is not None else None,
            "kb_relevant": kb_relevant,
            "total": len(cat),
        }, ensure_ascii=False))
    elif selected is None:
        print(f"fell open — load everything ({reason})", file=sys.stderr)
    else:
        for article_id in sorted(selected):
            print(article_id)

    return 1 if selected is None else 0


if __name__ == "__main__":
    sys.exit(main())
