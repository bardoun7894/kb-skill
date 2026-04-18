"""
SessionEnd hook — raw-copy the conversation transcript into the KB.

Pure file I/O, zero API calls. Writes the rendered transcript to
`raw/sessions/<date>-<short-sid>.md` and appends a one-line index entry
to `daily/<date>.md` under `## Sessions`.

Extraction/structuring is deferred to `/kb-compile`, which batches many
sessions into a single LLM call. That keeps per-session capture free and
lossless; the LLM spend happens on-demand, over material the user has
already decided is worth compiling.

Recursion guard: if we were spawned by a downstream Claude Code run, exit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

if os.environ.get("CLAUDE_INVOKED_BY"):
    sys.exit(0)

ROOT = Path(__file__).resolve().parent.parent
DAILY_DIR = ROOT / "daily"
RAW_SESSIONS_DIR = ROOT / "raw" / "sessions"
SCRIPTS_DIR = ROOT / "scripts"

logging.basicConfig(
    filename=str(SCRIPTS_DIR / "flush.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [hook] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

MAX_TURNS = 200
MIN_TURNS_TO_SAVE = 1


def find_transcript(session_id: str, hinted_path: str) -> Path | None:
    """Prefer the hint; fall back to globbing every project dir under ~/.claude/projects."""
    if hinted_path:
        p = Path(hinted_path)
        if p.exists():
            return p
    projects = Path.home() / ".claude" / "projects"
    if projects.is_dir():
        for candidate in projects.glob(f"*/{session_id}.jsonl"):
            return candidate
    return None


def extract_turns(transcript_path: Path) -> tuple[list[dict], str | None, str | None]:
    """Parse JSONL, return (turns, cwd, first_user_prompt)."""
    turns: list[dict] = []
    cwd: str | None = None
    first_user: str | None = None

    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if cwd is None and isinstance(entry.get("cwd"), str):
                cwd = entry["cwd"]

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = entry.get("role", "")
                content = entry.get("content", "")

            if role not in ("user", "assistant"):
                continue

            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                content = "\n".join(parts)

            if isinstance(content, str) and content.strip():
                turns.append({"role": role, "content": content.strip()})
                if first_user is None and role == "user":
                    first_user = content.strip()

    return turns[-MAX_TURNS:], cwd, first_user


def render_session(turns: list[dict], session_id: str, cwd: str | None) -> str:
    header = [
        f"# Session {session_id}",
        "",
        f"**Captured:** {datetime.now(timezone.utc).astimezone().isoformat()}",
        f"**cwd:** {cwd or 'unknown'}",
        f"**Turns:** {len(turns)}",
        "",
        "---",
        "",
    ]
    body = []
    for t in turns:
        label = "User" if t["role"] == "user" else "Assistant"
        body.append(f"## {label}\n\n{t['content']}\n")
    return "\n".join(header) + "\n".join(body)


def append_daily_index(
    date_str: str,
    time_str: str,
    cwd: str | None,
    first_user: str | None,
    raw_link: str,
) -> None:
    daily_file = DAILY_DIR / f"{date_str}.md"
    cwd_label = Path(cwd).name if cwd else "unknown"
    preview = (first_user or "").splitlines()[0][:80].replace("|", "¦").replace("[", "(").replace("]", ")")
    entry = f'- {time_str} [{cwd_label}] "{preview}" → [[{raw_link}]]\n'

    if not daily_file.exists():
        daily_file.write_text(
            f"# Daily Log: {date_str}\n\n## Sessions\n\n{entry}\n## Memory Maintenance\n",
            encoding="utf-8",
        )
        return

    text = daily_file.read_text(encoding="utf-8")

    # Idempotency: if this raw-link already appears, don't append again.
    if f"[[{raw_link}]]" in text:
        return

    if "## Sessions" not in text:
        daily_file.write_text(
            text.rstrip() + f"\n\n## Sessions\n\n{entry}",
            encoding="utf-8",
        )
        return

    # Insert the entry at the end of the ## Sessions section
    # (right before the next ## header, or EOF). Ensure a blank line
    # separates the list from the next heading per markdown convention.
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_sessions = False
    inserted = False

    for line in lines:
        if in_sessions and line.startswith("## ") and not inserted:
            out.append(entry)
            if not entry.endswith("\n\n"):
                out.append("\n")
            inserted = True
            in_sessions = False
        out.append(line)
        if line.strip() == "## Sessions":
            in_sessions = True

    if in_sessions and not inserted:
        if not out or not out[-1].endswith("\n"):
            out.append("\n")
        out.append(entry)
        inserted = True

    daily_file.write_text("".join(out), encoding="utf-8")


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        try:
            hook_input: dict = json.loads(raw_input)
        except json.JSONDecodeError:
            fixed = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw_input)
            hook_input = json.loads(fixed)
    except (json.JSONDecodeError, ValueError, EOFError) as e:
        logging.error("Failed to parse stdin: %s", e)
        return

    session_id = hook_input.get("session_id", "unknown")
    source = hook_input.get("source", "unknown")
    hinted = hook_input.get("transcript_path", "") or ""
    logging.info("SessionEnd fired: session=%s source=%s", session_id, source)

    transcript_path = find_transcript(session_id, hinted)
    if transcript_path is None:
        logging.info("SKIP: transcript not found (hint=%s)", hinted)
        return

    try:
        turns, cwd, first_user = extract_turns(transcript_path)
    except Exception as e:
        logging.error("Extraction failed: %s", e)
        return

    if len(turns) < MIN_TURNS_TO_SAVE:
        logging.info("SKIP: %d turns (min %d)", len(turns), MIN_TURNS_TO_SAVE)
        return

    now = datetime.now(timezone.utc).astimezone()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    RAW_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)

    short_sid = session_id.split("-")[0] if "-" in session_id else session_id[:8]
    raw_stem = f"{date_str}-{short_sid}"
    raw_file = RAW_SESSIONS_DIR / f"{raw_stem}.md"
    raw_file.write_text(render_session(turns, session_id, cwd), encoding="utf-8")

    append_daily_index(
        date_str,
        time_str,
        cwd,
        first_user,
        raw_link=f"raw/sessions/{raw_stem}",
    )

    logging.info(
        "Raw-copied session %s (%d turns, %d bytes) → %s",
        session_id,
        len(turns),
        raw_file.stat().st_size,
        raw_file,
    )


if __name__ == "__main__":
    main()
