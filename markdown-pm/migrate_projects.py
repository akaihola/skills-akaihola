#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["python-frontmatter>=1.1.0"]
# ///

import frontmatter
from pathlib import Path

projects_dir = Path("pages/Projects")

status_map = {
    "readfish.md": "Abandoned",
    "Darkgray.md": "Active",
    "GitHub README summarizer.md": "Active",
    "Evolving GitHub repository experiment.md": "Planning",
    "Jira create issue prefill.md": "On Hold",
    "Kielenrikastaja.md": "Active",
    "pgtricks.md": "Planning",
    "tkkylienhistoria.md": "Completed",
    "uv & NixOS.md": "Active",
    "Web AI assistant.md": "Active",
}

tags_map = {
    "readfish.md": ["web", "translation"],
    "Darkgray.md": ["github", "search"],
    "GitHub README summarizer.md": ["obsidian", "template", "github"],
    "Evolving GitHub repository experiment.md": ["github", "ai", "experiment"],
    "Jira create issue prefill.md": ["jira", "userscript", "javascript"],
    "Kielenrikastaja.md": ["finnish", "language", "ai"],
    "pgtricks.md": ["python", "rust", "packaging"],
    "tkkylienhistoria.md": ["finnish", "history", "ai"],
    "uv & NixOS.md": ["python", "nixos"],
    "Web AI assistant.md": ["github", "ai", "automation"],
}

for filename, status in status_map.items():
    filepath = projects_dir / filename

    if not filepath.exists():
        continue

    try:
        post = frontmatter.load(filepath)

        if "status" in post.metadata:
            continue

        post["type"] = "project"
        post["status"] = status
        post["priority"] = "P2"
        post["created"] = "2025-01-11"
        post["last_updated"] = "2025-01-11"
        post["tags"] = tags_map.get(filename, [])

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))

        print(f"✓ {filename}")
    except Exception as e:
        print(f"✗ {filename}: {e}")

print("\nDone!")