"""Jev triage for the kb-ingest inbox — which raw/ files deserve an LLM, and as what.

A mature `raw/` runs to hundreds of megabytes, overwhelmingly session transcripts.
Handing that pile to an LLM to sort is both expensive and the failure mode behind the
KB self-capture incident: the compiler ingesting its own output in a loop.

Three questions per file, in one request each (different files are different states,
so they fan out rather than batch):

  worth      ingest / skip / archive
  duplicate  is this already covered by an existing article
  kind       concept / source / entity / connection / qa

It is a *sorter*, not a deleter. Nothing here removes a file, and every uncertain or
unrecognised answer lands on `ingest` so a human or an LLM still sees it. A wrongly
skipped file is knowledge silently lost; a wrongly ingested one costs a few cents.

    python3 jev_triage.py                 # triage the whole un-ingested inbox
    python3 jev_triage.py --json          # machine-readable, for a hook
    python3 jev_triage.py raw/foo.md      # specific files
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jev
from config import LOG_FILE, RAW_DIR
from jev_gate import index_summaries

LOG_TAG = "kb-ingest"
TIMEOUT = float(os.environ.get("KB_INGEST_JEV_TIMEOUT", "15"))

# When --worth ingest sees a duplicate probability at or above this, the file is
# treated as already-covered and skipped from the printed output (and reported on
# stderr). Below it — or when Jev failed and duplicate is None — we lean to
# processing, because a wrongly-skipped file is knowledge silently lost while a
# wrongly-ingested one only costs a few cents.
DUP_SKIP = 0.9

# Enough of a file to judge it by, small enough to stay far under the 32k state cap.
HEAD_CHARS = 1500
TAIL_CHARS = 500

SKIP_NAMES = {".gitkeep", ".DS_Store"}
SKIP_DIRS = {"assets"}

WORTH_CRITERIA = {
    "ingest": (
        "Holds durable knowledge worth keeping: a decision and its rationale, an "
        "architecture, a gotcha that cost real time, a spec, research, or a solved bug."
    ),
    "skip": (
        "Nothing durable: routine tool calls, file listings, chit-chat, a session that "
        "went nowhere, boilerplate, or output this knowledge base itself generated "
        "(a compile log, a lint report, an ingest snapshot, a flush prompt)."
    ),
    "archive": (
        "Real content, but superseded, obsolete, or a duplicate of something newer — "
        "keep the file, do not build an article from it."
    ),
}

KIND_CRITERIA = {
    "concept": "A reusable pattern, technique, or lesson that generalizes beyond one event.",
    "source": "A document, transcript, or session captured largely as it stands.",
    "entity": "A specific tool, service, machine, person, or project being described.",
    "connection": "How two or more existing ideas relate, depend on, or break each other.",
    "qa": "A direct question and its answer.",
}

DUPLICATE_INSTRUCTIONS = (
    "The state lists the knowledge base's existing articles with a one-line summary each, "
    "plus an excerpt of a new incoming document. Is this document's substance already "
    "covered by one of those articles? Say yes only when an existing article clearly "
    "covers the same specific material — not merely the same general topic."
)


def excerpt(path: Path) -> str:
    """A cheap, bounded preview. Never reads a whole file — raw/ can be gigabytes."""
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(HEAD_CHARS)
            tail = ""
            if size > HEAD_CHARS + TAIL_CHARS:
                f.seek(max(0, size - TAIL_CHARS))
                tail = f.read(TAIL_CHARS)
    except OSError as exc:
        return f"(unreadable: {exc})"
    return f"{head}\n…\n{tail}" if tail else head


def already_ingested(path: Path) -> bool:
    """The skill's rule: a filename mentioned in knowledge/log.md has been processed."""
    try:
        return path.name in LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return False


def inbox() -> list[Path]:
    """Un-ingested files in raw/, smallest first."""
    files = []
    for path in sorted(RAW_DIR.rglob("*")):
        if not path.is_file() or path.name in SKIP_NAMES or path.name.startswith("."):
            continue
        if SKIP_DIRS & set(path.relative_to(RAW_DIR).parts):
            continue
        if already_ingested(path):
            continue
        files.append(path)
    return sorted(files, key=lambda p: p.stat().st_size)


def triage_one(path: Path, summaries: dict[str, str], have_key: bool = True) -> dict:
    """Three decisions about one file, in one request. Fails toward 'ingest'."""
    unknown = {
        "file": str(path),
        "worth": "ingest",
        "kind": None,
        "duplicate": None,
        "confidence": None,
        "fell_open": True,
    }
    if not have_key:
        return unknown

    state = {
        "filename": path.name,
        "path": str(path.relative_to(RAW_DIR.parent)),
        "size_bytes": path.stat().st_size,
        "excerpt": excerpt(path),
        "existing_articles": [{"id": k, "summary": v} for k, v in summaries.items()],
    }
    questions = {
        "worth": {
            "type": "choice",
            "instructions": "Should this incoming document become a knowledge base article?",
            "criteria": WORTH_CRITERIA,
        },
        "kind": {
            "type": "choice",
            "instructions": "If it were written up, which kind of article would it be?",
            "criteria": KIND_CRITERIA,
        },
        "duplicate": {"type": "noul", "instructions": DUPLICATE_INSTRUCTIONS},
    }

    answers = jev.ask(state, questions, tag=LOG_TAG, timeout=TIMEOUT)
    if not answers:
        return unknown

    worth = answers.get("worth") or {}
    kind = answers.get("kind") or {}
    dup = answers.get("duplicate") or {}
    choice = worth.get("choice")
    return {
        "file": str(path),
        # An unrecognised or missing verdict is not permission to drop the file.
        "worth": choice if choice in WORTH_CRITERIA else "ingest",
        "kind": kind.get("choice") if kind.get("choice") in KIND_CRITERIA else None,
        "duplicate": dup.get("noul") if isinstance(dup.get("noul"), (int, float)) else None,
        "confidence": worth.get("confidence"),
        "fell_open": False,
    }


def triage(paths: list[Path], workers: int = 8) -> list[dict]:
    """Fan out — different files are different states, so they cannot batch."""
    have_key = bool(jev.typesafe_key() or jev.api_key())
    summaries = index_summaries()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda p: triage_one(p, summaries, have_key), paths))


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="files to triage (default: the whole inbox)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="only the N smallest")
    parser.add_argument(
        "--worth",
        choices=sorted(WORTH_CRITERIA),
        help="print only the paths with this verdict, one per line — for shell callers. "
        "Prints nothing and exits 1 if triage could not run, so a caller can fall open.",
    )
    args = parser.parse_args()

    paths = [Path(p) for p in args.paths] if args.paths else inbox()
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print("nothing un-ingested in raw/", file=sys.stderr)
        return 0
    if not (jev.typesafe_key() or jev.api_key()):
        print("no API key — every file defaults to 'ingest'", file=sys.stderr)

    results = triage(paths)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    if args.worth:
        # Shell-caller mode. If every file fell open, triage did not actually run —
        # say so with exit 1 rather than handing back a list that means nothing, so
        # the caller can fall back to its own pre-Jev behaviour.
        if all(r["fell_open"] for r in results):
            print("triage unavailable — every file fell open", file=sys.stderr)
            return 1
        for r in results:
            if r["worth"] != args.worth:
                continue
            # A near-certain duplicate already exists — leave the file out so the
            # ingest caller doesn't have to repeat work Jev is sure is done. Report on
            # stderr so a human watching the run still sees what got skipped.
            if isinstance(r["duplicate"], (int, float)) and r["duplicate"] >= DUP_SKIP:
                print(f"dup-skip {r['file']} p={r['duplicate']:.2f}", file=sys.stderr)
                continue
            print(r["file"])
        return 0

    for kind in ("ingest", "archive", "skip"):
        rows = [r for r in results if r["worth"] == kind]
        if not rows:
            continue
        print(f"\n{kind.upper()} ({len(rows)})")
        for r in sorted(rows, key=lambda r: r["file"]):
            name = Path(r["file"]).relative_to(RAW_DIR.parent)
            bits = []
            if r["kind"]:
                bits.append(f"as {r['kind']}")
            if r["duplicate"] is not None and r["duplicate"] > 0.5:
                bits.append(f"dup p={r['duplicate']:.2f}")
            if isinstance(r["duplicate"], (int, float)) and r["duplicate"] >= DUP_SKIP:
                bits.append("dup-skip")
            if r["fell_open"]:
                bits.append("fell open")
            suffix = f"  [{', '.join(bits)}]" if bits else ""
            print(f"  {name}{suffix}")

    skipped = sum(1 for r in results if r["worth"] == "skip")
    print(f"\n{len(results)} files · {skipped} would not reach an LLM", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
