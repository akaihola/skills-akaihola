#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "python-frontmatter>=1.1.0",
#     "rich>=13.9.0",
#     "pathlib>=1.0",
# ]
# ///

import frontmatter
import argparse
from pathlib import Path
from datetime import datetime
from rich.console import Console
from rich import print as rprint
import sys

console = Console()


def update_project(filepath: Path, updates: dict) -> bool:
    try:
        post = frontmatter.load(filepath)

        for key, value in updates.items():
            post[key] = value

        post["last_updated"] = datetime.now().strftime("%Y-%m-%d")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(frontmatter.dumps(post))

        return True
    except Exception as e:
        console.print(f"[red]Error updating {filepath}: {e}[/red]")
        return False


def main():
    parser = argparse.ArgumentParser(description="Update project metadata safely")
    parser.add_argument("--file", required=True, help="Project file path or name")
    parser.add_argument(
        "--set",
        action="append",
        help="Set key=value pairs (can be used multiple times)",
    )
    parser.add_argument("--status", help="Set status (shortcut)")
    parser.add_argument("--priority", help="Set priority (shortcut)")
    parser.add_argument("--add-tag", action="append", help="Add a tag")
    parser.add_argument("--remove-tag", action="append", help="Remove a tag")

    args = parser.parse_args()

    filepath = Path(args.file)
    if not filepath.exists() and not str(filepath).endswith(".md"):
        filepath = Path(f"pages/Projects/{args.file}")

    if not filepath.exists():
        filepath = Path(f"pages/Projects/{args.file}.md")

    if not filepath.exists():
        console.print(f"[red]File not found: {args.file}[/red]")
        sys.exit(1)

    updates = {}

    if args.set:
        for item in args.set:
            if "=" not in item:
                console.print(f"[red]Invalid key=value pair: {item}[/red]")
                sys.exit(1)
            key, value = item.split("=", 1)
            updates[key.strip()] = value.strip()

    if args.status:
        updates["status"] = args.status

    if args.priority:
        updates["priority"] = args.priority

    if args.add_tag or args.remove_tag:
        try:
            post = frontmatter.load(filepath)
            existing_tags = set(post.get("tags", []))

            if args.add_tag:
                existing_tags.update(args.add_tag)

            if args.remove_tag:
                existing_tags.difference_update(args.remove_tag)

            updates["tags"] = sorted(list(existing_tags))
        except Exception as e:
            console.print(f"[red]Error loading file for tag updates: {e}[/red]")
            sys.exit(1)

    if not updates:
        console.print(
            "[yellow]No updates specified. Use --status, --priority, --set, or --add-tag[/yellow]"
        )
        sys.exit(0)

    success = update_project(filepath, updates)

    if success:
        console.print(f"[green]✓ Updated {filepath.name}[/green]")
        for key, value in updates.items():
            console.print(f"  {key}: {value}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
