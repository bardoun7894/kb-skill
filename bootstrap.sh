#!/bin/bash
# kb-skill bootstrap installer
#
# One-liner install from GitHub:
#   curl -fsSL https://raw.githubusercontent.com/bardoun7894/kb-skill/main/bootstrap.sh | bash
#
# What it does:
#   1. Clones (or updates) the kb-skill repo to ~/.local/share/kb-skill
#   2. Runs its install.sh, which copies the six kb-* skills into ~/.claude/skills/
#   3. Prints next steps

set -euo pipefail

REPO_URL="https://github.com/bardoun7894/kb-skill.git"
INSTALL_DIR="${KB_SKILL_DIR:-$HOME/.local/share/kb-skill}"

echo "kb-skill bootstrap"
echo "  repo:   $REPO_URL"
echo "  clone:  $INSTALL_DIR"
echo

if ! command -v git >/dev/null 2>&1; then
  echo "error: git is required but not installed" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "warning: uv is not installed. Install it with 'brew install uv' (or see https://github.com/astral-sh/uv) before running /kb-setup." >&2
fi

mkdir -p "$(dirname "$INSTALL_DIR")"

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "updating existing clone..."
  git -C "$INSTALL_DIR" fetch --quiet origin
  git -C "$INSTALL_DIR" reset --hard --quiet origin/main
else
  if [ -e "$INSTALL_DIR" ]; then
    echo "error: $INSTALL_DIR exists but is not a git repo. Move it aside and retry." >&2
    exit 1
  fi
  echo "cloning fresh..."
  git clone --quiet "$REPO_URL" "$INSTALL_DIR"
fi

echo
echo "running installer..."
bash "$INSTALL_DIR/install.sh" --force

echo
echo "bootstrap complete."
echo
echo "Next steps:"
echo "  1. cd into any project where you want a knowledge base"
echo "  2. Start a Claude Code session"
echo "  3. Run /kb-setup to initialize the KB and wire up auto-capture hooks"
echo "  4. Drop documents into ai-knowledge-base/raw/ and run /kb-ingest"
echo "  5. Ask questions with /kb-query \"your question\""
echo
echo "To update later, just re-run the curl one-liner."
