#!/usr/bin/env python3
"""Delete emails by message ID with safety preview."""

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
# ]
# ///

import json
import re
import subprocess
import sys

import rich.console
import rich.panel
import typer

ACCOUNT = "akaihola"


def run_himalaya(args: list[str], verbose: bool = False) -> subprocess.CompletedProcess:
    """Run a himalaya command and return result."""
    if verbose:
        console.print(f"[dim]Running: himalaya {' '.join(args)}[/dim]")

    result = subprocess.run(
        ["himalaya", *args],
        check=False, capture_output=True,
        text=True,
    )

    if result.returncode != 0 and args[0] != "envelope" and args[1] == "delete":
        console.print(f"[red]Error running himalaya:[/red] {result.stderr}")
        console.print(f"[red]Command:[/red] himalaya {' '.join(args)}")
        raise typer.Exit(1)

    return result


def is_interactive() -> bool:
    """Check if running in interactive terminal (not called by agent)."""
    return sys.stdin.isatty()


def parse_email_headers(message_text: str) -> dict:
    """Parse email headers from message text."""
    headers_end = message_text.find("\n\n")
    if headers_end == -1:
        headers_end = message_text.find("\n---\n")

    header_text = message_text[:headers_end] if headers_end > 0 else message_text

    headers = {}
    for line in header_text.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    return headers


def get_message(message_id: int, folder: str, verbose: bool = False) -> dict | None:
    """Get full message (headers + body) by ID."""
    result = run_himalaya(
        [
            "message",
            "read",
            "--account",
            ACCOUNT,
            "--folder",
            folder,
            "--preview",
            "--output",
            "json",
            str(message_id),
        ],
        verbose=verbose,
    )

    try:
        message_text = json.loads(result.stdout)
        if not isinstance(message_text, str):
            return None

        headers = parse_email_headers(message_text)

        headers_end = message_text.find("\n\n")
        if headers_end == -1:
            headers_end = message_text.find("\n---\n")
        body = (
            message_text[headers_end + 2 :].strip() if headers_end > 0 else message_text
        )

        envelope = {
            "id": str(message_id),
            "from": {},
            "to": {},
            "date": "",
            "subject": "",
        }

        if "from" in headers:
            from_match = re.match(r"^(.*?)\s*<([^>]+)>$", headers["from"])
            if from_match:
                envelope["from"] = {
                    "name": from_match.group(1).strip(),
                    "address": from_match.group(2).strip(),
                }
            elif "<" in headers["from"] and ">" in headers["from"]:
                email = re.search(r"<([^>]+)>", headers["from"])
                if email:
                    envelope["from"] = {"address": email.group(1)}
            else:
                envelope["from"] = {"address": headers["from"]}

        if "to" in headers:
            to_addrs = [addr.strip() for addr in headers["to"].split(",")]
            if len(to_addrs) == 1:
                to_match = re.match(r"^(.*?)\s*<([^>]+)>$", to_addrs[0])
                if to_match:
                    envelope["to"] = {
                        "name": to_match.group(1).strip(),
                        "address": to_match.group(2).strip(),
                    }
                elif "<" in to_addrs[0] and ">" in to_addrs[0]:
                    email = re.search(r"<([^>]+)>", to_addrs[0])
                    if email:
                        envelope["to"] = {"address": email.group(1)}
                else:
                    envelope["to"] = {"address": to_addrs[0]}
            else:
                envelope["to"] = []
                for to_addr in to_addrs:
                    to_match = re.match(r"^(.*?)\s*<([^>]+)>$", to_addr)
                    if to_match:
                        envelope["to"].append(
                            {
                                "name": to_match.group(1).strip(),
                                "address": to_match.group(2).strip(),
                            }
                        )
                    elif "<" in to_addr and ">" in to_addr:
                        email = re.search(r"<([^>]+)>", to_addr)
                        if email:
                            envelope["to"].append({"address": email.group(1)})
                    else:
                        envelope["to"].append({"address": to_addr})

        envelope["date"] = headers.get("date", "")
        envelope["subject"] = headers.get("subject", "")

        return {"envelope": envelope, "body": body}

    except json.JSONDecodeError:
        return None


def show_email_preview(email: dict) -> None:
    """Display email preview in a styled panel."""
    console = rich.console.Console(force_terminal=False)

    date_str = email.get("date", "N/A")
    from_data = email.get("from", {})
    from_name = from_data.get("name", "") if isinstance(from_data, dict) else ""
    from_addr = (
        from_data.get("address", "") if isinstance(from_data, dict) else from_data
    )
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

    console.print(f"[dim]Fetching message {message_id} from {folder}...[/dim]")
    message_data = get_message(message_id, folder, verbose=verbose)

    if not message_data:
        console.print()
        console.print(
            f"[red]❌ Error: Email with ID {message_id} not found in folder {folder}[/red]"
        )
        sys.exit(1)

    email = message_data["envelope"]
    show_email_preview(email)

    if not execute:
        console.print()
        console.print("[yellow]⚠️ DRY-RUN MODE[/yellow] - No changes made.")
        console.print()
        console.print("[dim]To actually delete this email, run:[/dim]")
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

    console.print(f"[dim]Deleting message {message_id}...[/dim]")

    result = run_himalaya(
        [
            "envelope",
            "delete",
            "--account",
            ACCOUNT,
            "--folder",
            folder,
            str(message_id),
        ],
        verbose=verbose,
    )

    if result.returncode == 0:
        console.print()
        console.print("[green]✅ Email deleted successfully[/green]")
    else:
        console.print()
        console.print("[red]❌ Delete failed[/red]")
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
