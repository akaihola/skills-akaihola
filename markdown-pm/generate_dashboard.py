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
import json
from pathlib import Path
from datetime import datetime
from textwrap import dedent


def load_projects(projects_dir: Path = Path("pages/Projects")):
    results = []
    if not projects_dir.exists():
        return results

    for f in projects_dir.glob("*.md"):
        try:
            post = frontmatter.load(f)
            metadata = post.metadata
            metadata["_file"] = f.name.replace(".md", "")
            metadata["_path"] = str(f)
            results.append(metadata)
        except Exception as e:
            print(f"Skipping {f.name}: {e}")
    return results


def format_status(status):
    emoji_map = {
        "Active": "🟢",
        "Completed": "✅",
        "On Hold": "🟡",
        "Planning": "🔵",
        "Abandoned": "⚪",
    }
    return f"{emoji_map.get(status, '❓')} {status}"


def generate_dashboard(projects, output_file=None):
    priority_order = {"P1": 0, "P2": 1, "P3": 2}
    active_projects = [p for p in projects if p.get("status") == "Active"]

    def get_last_updated(p):
        val = p.get("last_updated", "")
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d")
        return str(val)

    active_projects.sort(
        key=lambda p: (
            priority_order.get(p.get("priority", "P3"), 99),
            get_last_updated(p),
        )
    )

    all_projects_sorted = projects.copy()
    all_projects_sorted.sort(
        key=lambda p: (
            priority_order.get(p.get("priority", "P3"), 99),
            get_last_updated(p),
        )
    )

    recent_projects = sorted(projects, key=lambda p: get_last_updated(p), reverse=True)[
        :7
    ]

    status_counts = {}
    for p in projects:
        status = p.get("status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    content = dedent(
        """\
        # Project Dashboard

        > **Last updated:** {date}

        ## How to use this page

        - Treat **Active** as your hard WIP limit (ideally 1–2 projects).
        - **Active P1**: Primary focus. Move these weekly; prioritize in short sessions.
        - **Active P2**: Secondary focus. Optional/mood-based; fine to let drift.
        - Open quickly in Obsidian via Quick Switcher (Cmd/Ctrl+O) → “Project dashboard”, and consider bookmarking it.
        - Update project metadata using the `markdown-pm` scripts (don’t edit YAML by hand):

          ```bash
          .claude/skills/markdown-pm/update_project.py --file "<Project name>" --status "Active" --priority P2
          ```

        - After any project metadata changes, regenerate this dashboard:

          ```bash
          .claude/skills/markdown-pm/generate_dashboard.py --output "pages/PKB/Project dashboard.md"
          ```

        ## Summary

        """.format(date=datetime.now().strftime("%Y-%m-%d %H:%M"))
    )

    for status in ["Active", "Planning", "On Hold", "Completed", "Abandoned"]:
        count = status_counts.get(status, 0)
        emoji = (
            "🟢"
            if status == "Active"
            else "🔵"
            if status == "Planning"
            else "🟡"
            if status == "On Hold"
            else "✅"
            if status == "Completed"
            else "⚪"
        )
        content += f"- {emoji} **{status}:** {count}\n"

    content += "\n---\n\n"

    content += dedent(
        """\
        ## Active Projects

        | Project | Status | Priority | Updated | Tags |
        |---------|--------|----------|---------|------|
        """.lstrip()
    )

    for p in active_projects:
        tags_str = ", ".join(p.get("tags", [])[:3])
        if tags_str:
            tags_str = "`" + tags_str + "`"
        content += f"| [[{p.get('_file', '')}]] | {format_status(p.get('status', '-'))} | **{p.get('priority', '-')}** | {get_last_updated(p)} | {tags_str} |\n"

    content += "\n---\n\n"

    content += dedent("""\
        ## By Priority

        ### High Priority (P1)
        | Project | Status | Updated |
        |---------|--------|---------|
        """)

    for p in [p for p in all_projects_sorted if p.get("priority") == "P1"]:
        content += f"| [[{p.get('_file', '')}]] | {format_status(p.get('status', '-'))} | {get_last_updated(p)} |\n"

    content += "\n### Medium Priority (P2)\n| Project | Status | Updated |\n|---------|--------|---------|\n"
    for p in [p for p in all_projects_sorted if p.get("priority") == "P2"]:
        content += f"| [[{p.get('_file', '')}]] | {format_status(p.get('status', '-'))} | {get_last_updated(p)} |\n"

    content += "\n### Low Priority (P3)\n| Project | Status | Updated |\n|---------|--------|---------|\n"
    for p in [p for p in all_projects_sorted if p.get("priority") == "P3"]:
        content += f"| [[{p.get('_file', '')}]] | {format_status(p.get('status', '-'))} | {get_last_updated(p)} |\n"

    content += "\n---\n\n"

    content += dedent("""\
        ## Recently Updated

        | Project | Status | Updated |
        |---------|--------|---------|
        """)

    for p in recent_projects:
        content += f"| [[{p.get('_file', '')}]] | {format_status(p.get('status', '-'))} | {get_last_updated(p)} |\n"

    content += "\n---\n\n"
    content += "<!-- This dashboard is auto-generated. Edit individual project files instead. -->\n"

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"✓ Dashboard written to {output_file}")
    else:
        print(content)


def main():
    parser = argparse.ArgumentParser(description="Generate project dashboard")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument(
        "--projects-dir", default="pages/Projects", help="Projects directory path"
    )
    args = parser.parse_args()

    projects = load_projects(Path(args.projects_dir))
    generate_dashboard(projects, args.output)


if __name__ == "__main__":
    main()
