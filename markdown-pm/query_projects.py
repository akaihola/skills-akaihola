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
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def query_projects(projects_dir: Path = Path("pages/Projects")):
    results = []
    if not projects_dir.exists():
        rprint(f"[red]Projects directory not found: {projects_dir}")
        return results

    for f in projects_dir.glob("*.md"):
        try:
            post = frontmatter.load(f)
            metadata = post.metadata
            metadata["_file"] = f.name.replace(".md", "")
            metadata["_path"] = str(f)
            results.append(metadata)
        except Exception as e:
            console.print(f"[yellow]Skipping {f.name}: {e}[/yellow]")
    return results


def filter_projects(projects, args):
    filtered = projects

    if args.status:
        filtered = [p for p in filtered if p.get("status") == args.status]

    if args.priority:
        filtered = [p for p in filtered if p.get("priority") == args.priority]

    if args.tag:
        tags = args.tag.split(",")
        filtered = [
            p
            for p in filtered
            if p.get("tags") and any(tag in p.get("tags", []) for tag in tags)
        ]

    return filtered


def display_table(projects):
    if not projects:
        rprint("[yellow]No projects found matching criteria.[/yellow]")
        return

    table = Table(title="Projects")
    table.add_column("Project", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")
    table.add_column("Priority", style="yellow")
    table.add_column("Updated", style="green")

    for p in projects:
        status = p.get("status", "Unknown")
        status_icon = {
            "Active": "🟢",
            "Completed": "✅",
            "On Hold": "🟡",
            "Planning": "🔵",
            "Abandoned": "⚪",
        }.get(status, "❓")

        last_updated = p.get("last_updated", "-")
        if last_updated != "-" and not isinstance(last_updated, str):
            last_updated = str(last_updated)

        table.add_row(
            p.get("_file", ""),
            f"{status_icon} {status}",
            p.get("priority", "-"),
            last_updated,
        )

    console.print(table)


def display_json(projects):
    import json

    output = []
    for p in projects:
        output.append(
            {
                "project": p.get("_file"),
                "status": p.get("status"),
                "priority": p.get("priority"),
                "tags": p.get("tags", []),
                "last_updated": p.get("last_updated"),
            }
        )
    rprint(json.dumps(output, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Query projects from pages/Projects")
    parser.add_argument("--status", help="Filter by status")
    parser.add_argument("--priority", help="Filter by priority (P1, P2, P3)")
    parser.add_argument("--tag", help="Filter by tag (comma-separated)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--projects-dir", default="pages/Projects", help="Projects directory path"
    )
    args = parser.parse_args()

    projects = query_projects(Path(args.projects_dir))
    filtered = filter_projects(projects, args)

    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    filtered.sort(
        key=lambda p: (
            priority_order.get(p.get("priority", "P3"), 99),
            str(p.get("last_updated", "")),
        )
    )

    if args.json:
        display_json(filtered)
    else:
        display_table(filtered)


if __name__ == "__main__":
    main()
