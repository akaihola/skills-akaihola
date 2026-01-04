#!/usr/bin/env python3
"""Delete emails by message ID with safety preview."""

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

import rich.console
import rich.panel
import typer

ACCOUNT = "akaihola"


def run_himalaya(
    args: list[str], verbose: bool = False, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run himalaya via nix-shell and return result."""
    cmd = f"himalaya {' '.join(args)}"
    full_cmd = ["nix-shell", "-p", "himalaya", "--run", cmd]

    console = rich.console.Console(force_terminal=False)
    if verbose:
        console.print(f"[dim]Running: {' '.join(full_cmd)}[/dim]")

    return subprocess.run(full_cmd, capture_output=True, text=True, check=check)


def is_interactive() -> bool:
    """Check if running in interactive terminal (not called by agent)."""
    return sys.stdin.isatty()


def get_email_by_id(message_id: int, folder: str, verbose: bool = False) -> dict | None:
    """Get email details by message ID."""
    args = [
        "envelope",
        "list",
        "--account",
        ACCOUNT,
        "--folder",
        folder,
        "--output",
        "json",
    ]

    result = run_himalaya(args, verbose=verbose)
    envelopes = json.loads(result.stdout) if result.stdout.strip() else []

    for email in envelopes:
        if email.get("id") == message_id:
            return email

    return None


def show_email_preview(email: dict) -> None:
    """Display email preview in a styled panel."""
    console = rich.console.Console(force_terminal=False)

    date_str = email.get("date", "N/A")
    from_name = email.get("from", {}).get("name", "")
    from_addr = email.get("from", {}).get("addr", "")
    from_display = f"{from_name} <{from_addr}>" if from_name else from_addr
    subject = email.get("subject", "(no subject)")
    msg_id = email.get("id", "N/A")

    panel = rich.panel.Panel(
        f"[bold]Message ID:[/bold] {msg_id}\n"
        f"[bold]Date:[/bold] {date_str}\n"
        f"[bold]From:[/bold] {from_display}\n"
        f"[bold]Subject:[/bold] {subject}",
        title="[bold]📧 Email Preview[/bold]",
        border_style="red",
    )

    console.print()
    console.print(panel)


def delete_email(
    message_id: int, folder: str = "INBOX", execute: bool = False, verbose: bool = False
) -> None:
    """Delete email by message ID with safety checks."""
    console = rich.console.Console(force_terminal=False)

    email = get_email_by_id(message_id, folder, verbose=verbose)

    if not email:
        console.print()
        console.print(
            f"[red]❌ Error: Email with ID {message_id} not found in folder {folder}[/red]"
        )
        sys.exit(1)

    show_email_preview(email)

    if not execute:
        console.print()
        console.print("[yellow]⚠️ DRY-RUN MODE[/yellow] - No changes made.")
        console.print()
        console.print(f"[dim]To actually delete this email, run:[/dim]")
        console.print(
            f"[cyan]uv run scripts/email-delete.py {message_id} --folder {folder} --execute[/cyan]"
        )
        return

    console.print()

    if is_interactive():
        confirmed = typer.confirm(
            "[yellow]⚠️ Are you sure you want to delete this email?[/yellow]",
            default=False,
        )

        if not confirmed:
            console.print("[yellow]Delete cancelled.[/yellow]")
            return

    args = [
        "envelope",
        "delete",
        "--account",
        ACCOUNT,
        "--folder",
        folder,
        str(message_id),
    ]

    result = run_himalaya(args, verbose=verbose, check=False)

    if result.returncode == 0:
        console.print()
        console.print("[green]✅ Email deleted successfully[/green]")
    else:
        console.print()
        console.print(f"[red]❌ Delete failed[/red]")
        if result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        sys.exit(1)


def main(
    message_id: int, folder: str = "INBOX", execute: bool = False, verbose: bool = False
) -> None:
    """Delete email by message ID."""
    delete_email(message_id=message_id, folder=folder, execute=execute, verbose=verbose)


if __name__ == "__main__":
    app = typer.Typer()

    @app.command()
    def delete(
        message_id: int = typer.Argument(..., help="Message ID to delete"),
        folder: str = typer.Option("INBOX", "--folder", help="Folder to delete from"),
        execute: bool = typer.Option(
            False, "--execute", help="Actually perform deletion (default: dry-run)"
        ),
        verbose: bool = typer.Option(
            False, "-v", "--verbose", help="Show himalaya commands"
        ),
    ) -> None:
        main(message_id=message_id, folder=folder, execute=execute, verbose=verbose)

    app()
