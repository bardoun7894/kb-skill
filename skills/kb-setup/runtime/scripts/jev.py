"""TypeSafe Jev client — typed decisions (a label, a probability), never text.

Stdlib only. Every helper returns None on no key, HTTP/network error, a
malformed answer, low confidence, or JEV_DISABLED=1, so the caller always
keeps its existing path.

Key lookup is deliberately file-based, never shell-based: these scripts run under
Claude, pi, opencode, codex, gemini, the SessionEnd hooks and cron, and only some of
those inherit an exported shell variable. $OPENROUTER_API_KEY, else <kb-root>/.env,
else ~/.env, else the openrouter key in ~/.local/share/opencode/auth.json.
Input limit is 32k tokens — callers must not send bigger state.

Pass `tag=` to any helper to append each decision to $JEV_LOG_DIR/decisions.jsonl in
the `jev` CLI's own record shape, so `jev tune <tag>` can retrain the question.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

URL = os.environ.get("JEV_DECISIONS_URL", "https://openrouter.ai/api/alpha/decisions")
MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.13")
TIMEOUT_S = 8.0

ROOT_DIR = Path(__file__).resolve().parent.parent


def _key_from_env_file(path: Path) -> str:
    """Read OPENROUTER_API_KEY out of a .env file without importing dotenv."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export").strip() == "OPENROUTER_API_KEY":
                return value.strip().strip("'\"")
    except OSError:
        pass
    return ""


def api_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    for candidate in (ROOT_DIR / ".env", Path.home() / ".env"):
        key = _key_from_env_file(candidate)
        if key:
            return key
    try:
        with open(os.path.expanduser("~/.local/share/opencode/auth.json"), encoding="utf-8") as f:
            key = ((json.load(f).get("openrouter") or {}).get("key") or "").strip()
    except (OSError, ValueError, AttributeError):
        return None
    return key or None


def typesafe_key() -> str | None:
    """Direct TypeSafe key (same request/response shape): env, then ~/.config/typesafe/api_key."""
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(os.path.expanduser("~/.config/typesafe/api_key"), encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def log_decisions(state, answers: dict, questions: dict, tag: str) -> None:
    """Append one record per decision, in the `jev` CLI's shape. Never raises."""
    try:
        path = Path(os.environ.get("JEV_LOG_DIR") or "~/.local/state/jev").expanduser()
        path.mkdir(parents=True, exist_ok=True)
        blob = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False, sort_keys=True)
        state_hash = hashlib.sha1(blob.encode()).hexdigest()[:12]
        now = int(time.time())
        with (path / "decisions.jsonl").open("a", encoding="utf-8") as f:
            for name, answer in answers.items():
                question = questions.get(name)
                if question is None or not isinstance(answer, dict):
                    continue
                kind = answer.get("type")
                did = hashlib.sha1(f"{time.time_ns()}{tag}{blob}{name}".encode()).hexdigest()[:12]
                f.write(json.dumps({
                    "kind_of_record": "decision", "id": did, "ts": now, "tag": tag,
                    "state_hash": state_hash, "state_preview": blob[:600],
                    "question": question, "kind": kind,
                    "value": answer.get(kind) if kind in ("choice", "noul", "score") else None,
                    "confidence": answer.get("confidence"),
                }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def ask(state, questions: dict, tag: str | None = None, timeout: float | None = None) -> dict | None:
    """One request, several questions on the same state. Returns the answers dict or None.

    `timeout` overrides TIMEOUT_S — a wide batch (one question per article) takes
    materially longer than a single decision, and timing out means falling back to the
    expensive path, so those callers pass a larger value.
    """
    if os.environ.get("JEV_DISABLED") == "1":
        return None
    direct = typesafe_key()
    key = direct or api_key()
    if not key:
        return None
    url = os.environ.get("JEV_DECISIONS_URL", "https://api.typesafe.ai/v1/systemone") if direct else URL
    model = os.environ.get("JEV_MODEL", "jev-latest") if direct else MODEL
    req = urllib.request.Request(
        url,
        data=json.dumps({"model": model, "state": state, "questions": questions}).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # urllib's default User-Agent gets Cloudflare error 1010.
            "User-Agent": "kb-skill-jev/1.0",
            "X-Title": "kb-skill",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout or TIMEOUT_S) as r:
            answers = json.loads(r.read().decode()).get("answers")
    except Exception:
        return None
    if not isinstance(answers, dict):
        return None
    if tag:
        log_decisions(state, answers, questions, tag)
    return answers


def choice(state, instructions: str, criteria: dict[str, str], bar: float, tag: str | None = None) -> str | None:
    """The chosen label if confidence >= bar, else None."""
    answers = ask(state, {"q": {"type": "choice", "instructions": instructions, "criteria": criteria}}, tag=tag)
    a = (answers or {}).get("q") or {}
    label, conf = a.get("choice"), a.get("confidence")
    if label not in criteria or not isinstance(conf, (int, float)) or conf < bar:
        return None
    return label


def noul(state, instructions: str, tag: str | None = None) -> float | None:
    """Probability (0..1) that the statement holds, or None."""
    answers = ask(state, {"q": {"type": "noul", "instructions": instructions}}, tag=tag)
    v = ((answers or {}).get("q") or {}).get("noul")
    return float(v) if isinstance(v, (int, float)) else None
