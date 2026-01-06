#!/usr/bin/env python3
"""Search emails by sender, subject, date range, or folder."""

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
from datetime import date

import rich.console
import rich.panel
import rich.table

ACCOUNT = "akaihola"
MAX_LIMIT = 100
DEFAULT_PAGE_SIZE = 500
UNLIMITED_PAGE_SIZE = 10000
DEFAULT_PAGE_SIZE = 500
UNLIMITED_PAGE_SIZE = 10000


def run_himalaya(args: list[str], page_size: int, verbose: bool = False) -> list[dict]:
    """Run himalaya and return parsed JSON output."""
    cmd = ["himalaya"] + args

    if verbose:
        rich.console.Console().print(f"[dim]Running: {' '.join(cmd)}[/dim]")

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    if result.stdout.strip():
        return json.loads(result.stdout)
    return []


def search_emails(
    folder: str = "INBOX",
    from_filter: str | None = None,
    subject: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 20,
    no_limit: bool = False,
    verbose: bool = False,
) -> None:
    """Search emails and display results."""
    console = rich.console.Console(force_terminal=False)

    effective_limit = None if no_limit else min(limit, MAX_LIMIT)
    page_size = UNLIMITED_PAGE_SIZE if no_limit else DEFAULT_PAGE_SIZE

    args = [
        "envelope",
        "list",
        "--account",
        ACCOUNT,
        "--folder",
        folder,
        "--page-size",
        str(page_size),
        "--output",
        "json",
    ]

    envelopes = run_himalaya(args, page_size, verbose)

    results: list[dict] = []

    for email in envelopes:
        if from_filter:
            from_field = email.get("from") or {}
            from_name = (from_field.get("name") or "").lower()
            from_addr = (from_field.get("addr") or "").lower()
            from_search = from_filter.lower()
            if from_search not in from_name and from_search not in from_addr:
                continue

        if subject:
            subject_text = email.get("subject", "").lower()
            subject_search = subject.lower()
            if subject_search not in subject_text:
                continue

        if date_start:
            email_date_str = email.get("date", "")[:10]
            if email_date_str < date_start:
                continue

        if date_end:
            email_date_str = email.get("date", "")[:10]
            if email_date_str > date_end:
                continue

        results.append(email)

    if effective_limit:
        results = results[:effective_limit]

    if results:
        criteria_parts = []
        if from_filter:
            criteria_parts.append(f"From: {from_filter}")
        if subject:
            criteria_parts.append(f"Subject: {subject}")
        if date_start:
            criteria_parts.append(f"Since: {date_start}")
        if date_end:
            criteria_parts.append(f"Until: {date_end}")
        if effective_limit:
            criteria_parts.append(f"Limit: {effective_limit}")

        criteria_text = " | ".join(criteria_parts) if criteria_parts else "No filters"

        panel = rich.panel.Panel(
            f"[bold]Search Results[/bold] - {len(results)} email(s) found\n\n[dim]{criteria_text}[/dim]",
            border_style="green",
        )
        console.print()
        console.print(panel)

        table = rich.table.Table(
            show_header=True,
            show_edge=True,
        )
        table.add_column("Date", style="cyan", width=12)
        table.add_column("From", style="green")
        table.add_column("Subject", style="yellow")
        table.add_column("ID", style="magenta", width=8)

        for email in results:
            date_str = email.get("date", "N/A")[:10]
            from_field = email.get("from") or {}
            from_name = from_field.get("name", "")
            from_addr = from_field.get("addr", "")
            from_display = f"{from_name} <{from_addr}>" if from_name else from_addr
            subject = email.get("subject", "(no subject)")
            msg_id = email.get("id", "N/A")

            table.add_row(date_str, from_display, subject, str(msg_id))

        console.print(table)
    else:
        console.print()
        console.print("[yellow]No emails found matching the criteria.[/yellow]")


def main(
    folder: str = "INBOX",
    from_filter: str | None = None,
    subject: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    limit: int = 20,
    no_limit: bool = False,
    verbose: bool = False,
) -> None:
    """Search emails by various criteria."""
    search_emails(
        folder=folder,
        from_filter=from_filter,
        subject=subject,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
        no_limit=no_limit,
        verbose=verbose,
    )


if __name__ == "__main__":
    import typer

    app = typer.Typer()

    @app.command()
    def search(
        folder: str = typer.Option("INBOX", "--folder", help="Folder to search"),
        from_filter: str | None = typer.Option(None, "--from", help="Filter by sender"),
        subject: str | None = typer.Option(None, "--subject", help="Filter by subject"),
        date_start: str | None = typer.Option(
            None, "--date-start", help="Start date (YYYY-MM-DD)"
        ),
        date_end: str | None = typer.Option(
            None, "--date-end", help="End date (YYYY-MM-DD)"
        ),
        limit: int = typer.Option(
            20, "--limit", help="Maximum results (default: 20, capped at 100)"
        ),
        no_limit: bool = typer.Option(
            False, "--no-limit", help="Bypass the 100-result limit cap"
        ),
        verbose: bool = typer.Option(
            False, "-v", "--verbose", help="Show himalaya commands"
        ),
    ) -> None:
        main(
            folder=folder,
            from_filter=from_filter,
            subject=subject,
            date_start=date_start,
            date_end=date_end,
            limit=limit,
            no_limit=no_limit,
            verbose=verbose,
        )

    app()
