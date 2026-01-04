#!/usr/bin/env python3
"""Get daily email summary from INBOX and Sent folders."""

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
# ]
# ///

import subprocess
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import rich.console
import rich.panel
import rich.table

ACCOUNT = "akaihola"


def run_himalaya(args: list[str], verbose: bool = False) -> list[dict]:
    """Run himalaya via nix-shell and return parsed JSON output."""
    cmd = f"himalaya {' '.join(args)}"
    full_cmd = ["nix-shell", "-p", "himalaya", "--run", cmd]

    if verbose:
        rich.console.Console().print(f"[dim]Running: {' '.join(full_cmd)}[/dim]")

    result = subprocess.run(full_cmd, capture_output=True, text=True, check=True)

    if result.stdout.strip():
        return json.loads(result.stdout)
    return []


def get_email_summary(verbose: bool = False) -> None:
    """Display emails from past 24 hours."""
    console = rich.console.Console(force_terminal=False)

    today = date.today()
    yesterday = today - timedelta(days=1)

    for folder_name, folder_icon in [("INBOX", "📥"), ("Sent", "📤")]:
        args = [
            "envelope",
            "list",
            "--account",
            ACCOUNT,
            "--folder",
            folder_name,
            "--output",
            "json",
        ]

        envelopes = run_himalaya(args, verbose)

        recent_emails = [
            e
            for e in envelopes
            if e.get("date", "").startswith(today.isoformat())
            or e.get("date", "").startswith(yesterday.isoformat())
        ]

        if recent_emails:
            panel = rich.panel.Panel(
                f"[bold]{folder_icon} {folder_name}[/bold] ({len(recent_emails)} emails)",
                border_style="blue",
            )
            console.print()

            table = rich.table.Table(
                title=f"{folder_icon} {folder_name}",
                show_header=True,
                show_edge=True,
            )
            table.add_column("Date", style="cyan", width=12)
            table.add_column("From", style="green")
            table.add_column("Subject", style="yellow")
            table.add_column("ID", style="magenta", width=8)

            for email in sorted(
                recent_emails, key=lambda e: e.get("date", ""), reverse=True
            ):
                date_str = email.get("date", "N/A")[:10]
                from_name = email.get("from", {}).get("name", "")
                from_addr = email.get("from", {}).get("addr", "")
                from_display = f"{from_name} <{from_addr}>" if from_name else from_addr
                subject = email.get("subject", "(no subject)")
                msg_id = email.get("id", "N/A")

                table.add_row(date_str, from_display, subject, str(msg_id))

            console.print(panel)
            console.print(table)


def main(verbose: bool = False) -> None:
    """Get daily email summary."""
    get_email_summary(verbose=verbose)


if __name__ == "__main__":
    import typer

    typer.run(main)
