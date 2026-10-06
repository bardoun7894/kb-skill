"""
Lint the knowledge base for structural and semantic health.

Runs 8 checks: broken links, orphan pages, orphan sources, stale articles,
missing backlinks, sparse articles, duplicates (Jev), and contradictions (LLM).

Usage:
    uv run python lint.py                    # all checks
    uv run python lint.py --structural-only  # skip LLM checks (faster, cheaper)
"""

from __future__ import annotations

import argparse
import asyncio
import re
from itertools import combinations
from pathlib import Path

import jev
import kb_supersede

from config import ARTICLE_TYPES, KNOWLEDGE_DIR, REPORTS_DIR, now_iso, today_iso
from utils import (
    count_inbound_links,
    extract_wikilinks,
    file_hash,
    get_article_word_count,
    list_raw_files,
    list_wiki_articles,
    load_state,
    parse_frontmatter,
    read_all_wiki_content,
    save_state,
    wiki_article_exists,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def check_broken_links() -> list[dict]:
    """Check for [[wikilinks]] that point to non-existent articles."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue  # daily log references are valid
            if not wiki_article_exists(link):
                issues.append({
                    "severity": "error",
                    "check": "broken_link",
                    "file": str(rel),
                    "detail": f"Broken link: [[{link}]] - target does not exist",
                })
    return issues


def check_orphan_pages() -> list[dict]:
    """Check for articles with zero inbound links."""
    issues = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        link_target = str(rel).replace(".md", "").replace("\\", "/")
        inbound = count_inbound_links(link_target)
        if inbound == 0:
            issues.append({
                "severity": "warning",
                "check": "orphan_page",
                "file": str(rel),
                "detail": f"Orphan page: no other articles link to [[{link_target}]]",
            })
    return issues


def check_orphan_sources() -> list[dict]:
    """Check for daily logs that haven't been compiled yet."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        if log_path.name not in ingested:
            issues.append({
                "severity": "warning",
                "check": "orphan_source",
                "file": f"daily/{log_path.name}",
                "detail": f"Uncompiled daily log: {log_path.name} has not been ingested",
            })
    return issues


def check_stale_articles() -> list[dict]:
    """Check if source daily logs have changed since compilation."""
    state = load_state()
    ingested = state.get("ingested", {})
    issues = []
    for log_path in list_raw_files():
        rel = log_path.name
        if rel in ingested:
            stored_hash = ingested[rel].get("hash", "")
            current_hash = file_hash(log_path)
            if stored_hash != current_hash:
                issues.append({
                    "severity": "warning",
                    "check": "stale_article",
                    "file": f"daily/{rel}",
                    "detail": f"Stale: {rel} has changed since last compilation",
                })
    return issues


def check_missing_backlinks() -> list[dict]:
    """Check for asymmetric links: A links to B but B doesn't link to A."""
    issues = []
    for article in list_wiki_articles():
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(KNOWLEDGE_DIR)
        source_link = str(rel).replace(".md", "").replace("\\", "/")

        for link in extract_wikilinks(content):
            if link.startswith("daily/"):
                continue
            target_path = KNOWLEDGE_DIR / f"{link}.md"
            if target_path.exists():
                target_content = target_path.read_text(encoding="utf-8")
                if f"[[{source_link}]]" not in target_content:
                    issues.append({
                        "severity": "suggestion",
                        "check": "missing_backlink",
                        "file": str(rel),
                        "detail": f"[[{source_link}]] links to [[{link}]] but not vice versa",
                        "auto_fixable": True,
                    })
    return issues


REQUIRED_FRONTMATTER_KEYS = ("name", "description", "type")
TYPE_TO_DIR = {
    "concept": "concepts",
    "connection": "connections",
    "source": "sources",
    "entity": "entities",
    "qa": "qa",
}


def check_frontmatter_schema() -> list[dict]:
    """Validate each article's frontmatter against the unified schema."""
    issues = []
    for article in list_wiki_articles():
        rel = article.relative_to(KNOWLEDGE_DIR)
        content = article.read_text(encoding="utf-8")
        meta = parse_frontmatter(content)
        if meta is None:
            issues.append({
                "severity": "error",
                "check": "frontmatter_schema",
                "file": str(rel),
                "detail": "Missing YAML frontmatter block",
            })
            continue
        missing = [k for k in REQUIRED_FRONTMATTER_KEYS if k not in meta or not meta.get(k)]
        if missing:
            issues.append({
                "severity": "error",
                "check": "frontmatter_schema",
                "file": str(rel),
                "detail": f"Missing required frontmatter keys: {', '.join(missing)}",
            })
        article_type = meta.get("type")
        if article_type and article_type not in ARTICLE_TYPES:
            issues.append({
                "severity": "error",
                "check": "frontmatter_schema",
                "file": str(rel),
                "detail": f"Invalid type '{article_type}' (expected one of: {', '.join(ARTICLE_TYPES)})",
            })
        expected_dir = TYPE_TO_DIR.get(article_type or "")
        if expected_dir and rel.parts and rel.parts[0] != expected_dir:
            issues.append({
                "severity": "warning",
                "check": "frontmatter_schema",
                "file": str(rel),
                "detail": f"type '{article_type}' should live under {expected_dir}/, not {rel.parts[0]}/",
            })
    return issues


def check_sparse_articles() -> list[dict]:
    """Check for articles with fewer than 200 words."""
    issues = []
    for article in list_wiki_articles():
        word_count = get_article_word_count(article)
        if word_count < 200:
            rel = article.relative_to(KNOWLEDGE_DIR)
            issues.append({
                "severity": "suggestion",
                "check": "sparse_article",
                "file": str(rel),
                "detail": f"Sparse article: {word_count} words (minimum recommended: 200)",
            })
    return issues


# Duplicates = the "resolve" step of KG construction (anthropics/claude-cookbooks,
# capabilities/knowledge_graph): two current articles about the same thing. Not
# supersession (kb_supersede.py), where a newer article makes an older one wrong.
DUP_STOP = {"the", "a", "an", "to", "of", "and", "in", "on", "for", "is", "with", "vs", "from",
            "by", "at", "as", "or", "it", "its", "via", "how", "what", "no", "not", "why"}
DUP_SLUG_MIN = 0.4      # slug-word Jaccard; measured: 12 candidate pairs of 4,560 on 96 articles
DUP_SUMMARY_MIN = 0.3   # summary-word Jaccard
DUP_REPORT_MIN = 0.7

DUP_RUBRIC = (
    "The state lists a knowledge base's articles, each with a one-line summary. Each "
    "question names two of them as 'a=<id> b=<id>'.\n\n"
    "Answer: do these two articles cover the SAME subject, so a reader would be better "
    "served by one merged article?\n\n"
    "Say yes when both describe the same system, decision, bug, or pattern, even with "
    "different wording or emphasis. Say NO when they are different systems that share "
    "vocabulary, when one is a general pattern and the other a specific instance of it, "
    "or when one is a bug and the other its separate follow-up work."
)


def _dup_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in DUP_STOP and len(w) > 1}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def duplicate_candidates(arts: dict[str, dict]) -> list[tuple[str, str]]:
    """Pairs with overlapping slugs or summaries. Deterministic, free.

    A source and an article compiled from it overlap by design, so source/non-source
    pairs are never candidates. Redirects and superseded articles are already resolved.
    """
    live = sorted(k for k, v in arts.items()
                  if v.get("status") != "superseded"
                  and not kb_supersede.REDIRECT.search(v["summary"] or ""))
    pairs = []
    for a, b in combinations(live, 2):
        if a.startswith("sources/") != b.startswith("sources/"):
            continue
        slug = _jaccard(_dup_tokens(a.split("/")[-1]), _dup_tokens(b.split("/")[-1]))
        summ = _jaccard(_dup_tokens(arts[a]["summary"]), _dup_tokens(arts[b]["summary"]))
        if slug >= DUP_SLUG_MIN or summ >= DUP_SUMMARY_MIN:
            pairs.append((a, b))
    return pairs


def check_duplicates() -> list[dict]:
    """Jev judges each candidate pair. Jev unavailable -> report candidates as unverified."""
    arts = kb_supersede.load_articles()
    pairs = duplicate_candidates(arts)
    if not pairs:
        return []
    catalog = [{"id": k, "summary": v["summary"]} for k, v in sorted(arts.items())]
    issues = []
    for start in range(0, len(pairs), kb_supersede.CHUNK):
        chunk = pairs[start:start + kb_supersede.CHUNK]
        questions = {f"p{i}": {"type": "noul", "instructions": f"a={a} b={b}"}
                     for i, (a, b) in enumerate(chunk)}
        answers = jev.ask({"task": DUP_RUBRIC, "articles": catalog}, questions,
                          tag="kb-lint-duplicates", timeout=30)
        for i, (a, b) in enumerate(chunk):
            ans = (answers or {}).get(f"p{i}")
            p = ans.get("noul") if isinstance(ans, dict) else None
            if not isinstance(p, (int, float)):
                issues.append({
                    "severity": "suggestion",
                    "check": "duplicate",
                    "file": f"{a}.md",
                    "detail": f"Possible duplicate of [[{b}]] (unverified: Jev unavailable)",
                })
            elif p >= DUP_REPORT_MIN:
                issues.append({
                    "severity": "warning",
                    "check": "duplicate",
                    "file": f"{a}.md",
                    "detail": f"Likely duplicate of [[{b}]] (p={p:.2f}); merge into one",
                })
    return issues


async def check_contradictions() -> list[dict]:
    """Use LLM to detect contradictions across articles."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    wiki_content = read_all_wiki_content()

    prompt = f"""Review this knowledge base for contradictions, inconsistencies, or
conflicting claims across articles.

## Knowledge Base

{wiki_content}

## Instructions

Look for:
- Direct contradictions (article A says X, article B says not-X)
- Inconsistent recommendations (different articles recommend conflicting approaches)
- Outdated information that conflicts with newer entries

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES

Do NOT output anything else - no preamble, no explanation, just the formatted lines."""

    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(ROOT_DIR),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
    except Exception as e:
        return [{"severity": "error", "check": "contradiction", "file": "(system)", "detail": f"LLM check failed: {e}"}]

    issues = []
    if "NO_ISSUES" not in response:
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("CONTRADICTION:") or line.startswith("INCONSISTENCY:"):
                issues.append({
                    "severity": "warning",
                    "check": "contradiction",
                    "file": "(cross-article)",
                    "detail": line,
                })

    return issues


def generate_report(all_issues: list[dict]) -> str:
    """Generate a markdown lint report."""
    errors = [i for i in all_issues if i["severity"] == "error"]
    warnings = [i for i in all_issues if i["severity"] == "warning"]
    suggestions = [i for i in all_issues if i["severity"] == "suggestion"]

    lines = [
        f"# Lint Report - {today_iso()}",
        "",
        f"**Total issues:** {len(all_issues)}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Suggestions: {len(suggestions)}",
        "",
    ]

    for severity, issues, marker in [
        ("Errors", errors, "x"),
        ("Warnings", warnings, "!"),
        ("Suggestions", suggestions, "?"),
    ]:
        if issues:
            lines.append(f"## {severity}")
            lines.append("")
            for issue in issues:
                fixable = " (auto-fixable)" if issue.get("auto_fixable") else ""
                lines.append(f"- **[{marker}]** `{issue['file']}` - {issue['detail']}{fixable}")
            lines.append("")

    if not all_issues:
        lines.append("All checks passed. Knowledge base is healthy.")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Lint the knowledge base")
    parser.add_argument(
        "--structural-only",
        action="store_true",
        help="Skip LLM-based checks (contradictions) - faster and free",
    )
    args = parser.parse_args()

    print("Running knowledge base lint checks...")
    all_issues: list[dict] = []

    # Structural checks (free, instant)
    checks = [
        ("Broken links", check_broken_links),
        ("Orphan pages", check_orphan_pages),
        ("Orphan sources", check_orphan_sources),
        ("Stale articles", check_stale_articles),
        ("Frontmatter schema", check_frontmatter_schema),
        ("Missing backlinks", check_missing_backlinks),
        ("Sparse articles", check_sparse_articles),
        ("Duplicates (Jev)", check_duplicates),
    ]

    for name, check_fn in checks:
        print(f"  Checking: {name}...")
        issues = check_fn()
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")

    # LLM check (costs money)
    if not args.structural_only:
        print("  Checking: Contradictions (LLM)...")
        issues = asyncio.run(check_contradictions())
        all_issues.extend(issues)
        print(f"    Found {len(issues)} issue(s)")
    else:
        print("  Skipping: Contradictions (--structural-only)")

    # Generate and save report
    report = generate_report(all_issues)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"lint-{today_iso()}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_path}")

    # Update state
    state = load_state()
    state["last_lint"] = now_iso()
    save_state(state)

    # Summary
    errors = sum(1 for i in all_issues if i["severity"] == "error")
    warnings = sum(1 for i in all_issues if i["severity"] == "warning")
    suggestions = sum(1 for i in all_issues if i["severity"] == "suggestion")
    print(f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions")

    if errors > 0:
        print("\nErrors found - knowledge base needs attention!")
        return 1
    return 0


if __name__ == "__main__":
    exit(main())
