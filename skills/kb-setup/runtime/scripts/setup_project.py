#!/usr/bin/env python3
"""Auto-setup script to add memory compiler hooks to any project."""

import json
import sys
from pathlib import Path

KB_PATH = Path(__file__).parent.parent.resolve()
HOOKS_CONFIG = {
    "hooks": {
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python {KB_PATH}/hooks/session-start.py",
                        "timeout": 15,
                    }
                ],
            }
        ],
        "PreCompact": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python {KB_PATH}/hooks/pre-compact.py",
                        "timeout": 10,
                    }
                ],
            }
        ],
        "SessionEnd": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": f"python {KB_PATH}/hooks/session-end.py",
                        "timeout": 10,
                    }
                ],
            }
        ],
    }
}


def setup_project(project_path: str) -> None:
    project = Path(project_path).resolve()

    if not project.exists():
        print(f"Error: {project} does not exist")
        sys.exit(1)

    claude_dir = project / ".claude"
    claude_dir.mkdir(exist_ok=True)

    settings_file = claude_dir / "settings.json"

    if settings_file.exists():
        with open(settings_file) as f:
            existing = json.load(f)
        if "hooks" in existing:
            print(f"⚠️  {project.name} already has hooks. Merging...")
            existing["hooks"] = HOOKS_CONFIG["hooks"]
            with open(settings_file, "w") as f:
                json.dump(existing, f, indent=2)
            print(f"✅ Updated hooks in {project.name}")
        else:
            existing.update(HOOKS_CONFIG)
            with open(settings_file, "w") as f:
                json.dump(existing, f, indent=2)
            print(f"✅ Added hooks to {project.name}")
    else:
        with open(settings_file, "w") as f:
            json.dump(HOOKS_CONFIG, f, indent=2)
        print(f"✅ Created settings.json in {project.name}")

    print(f"\n📁 Knowledge base: {KB_PATH}")
    print(f"🔗 Project linked: {project.name}")
    print("\n💡 Open Obsidian vault at: knowledge/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python setup.py /path/to/project")
        print("Example: python setup.py ~/my-other-project")
        sys.exit(1)

    setup_project(sys.argv[1])
