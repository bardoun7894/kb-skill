#!/bin/bash
# kb-skill installer — copies the eight kb-* skills into ~/.claude/skills/
#
# Usage:
#   ./install.sh                  # copy all eight skills
#   ./install.sh --dry-run        # show what would be copied
#   ./install.sh --force          # overwrite existing installs without prompting

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
SKILLS_SRC="$REPO_ROOT/skills"
SKILLS_DST="$HOME/.claude/skills"

DRY_RUN=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --force)   FORCE=1   ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

if [ ! -d "$SKILLS_SRC" ]; then
  echo "error: $SKILLS_SRC does not exist" >&2
  exit 1
fi

mkdir -p "$SKILLS_DST"

SKILLS=(kb-setup kb-ingest kb-docs-sync kb-compile kb-query kb-lint kb-publish kb-spec)

echo "kb-skill installer"
echo "  source:      $SKILLS_SRC"
echo "  destination: $SKILLS_DST"
echo

for skill in "${SKILLS[@]}"; do
  src="$SKILLS_SRC/$skill"
  dst="$SKILLS_DST/$skill"

  if [ ! -d "$src" ]; then
    echo "  skip: $skill (source missing at $src)"
    continue
  fi

  if [ -d "$dst" ] && [ "$FORCE" -eq 0 ] && [ "$DRY_RUN" -eq 0 ]; then
    read -p "  $skill already installed at $dst. Overwrite? [y/N] " yn
    case "$yn" in
      [Yy]*) ;;
      *) echo "  skipped."; continue ;;
    esac
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would install: $skill"
  else
    rm -rf "$dst"
    cp -R "$src" "$dst"
    echo "  installed:     $skill"
  fi
done

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "dry run complete. re-run without --dry-run to apply."
else
  echo "done. next: run /kb-setup inside a project to initialize a knowledge base."
fi
