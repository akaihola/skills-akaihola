#!/usr/bin/env nix-shell
#!nix-shell -i python3 -p python312 python312Packages.typer python312Packages.rich

from pathlib import Path
import json
import subprocess
import sys
import re
import shutil
from datetime import datetime
from textwrap import dedent
from typing import Literal

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

app = typer.Typer(help="Save emails to files in various formats")
console = Console()

ACCOUNT = "akaihola"


def run_himalaya(args: list[str], verbose: bool = False) -> subprocess.CompletedProcess:
    """Run a himalaya command and return the result."""
    if verbose:
        console.print(f"[dim]Running: himalaya {' '.join(args)}[/dim]")

    result = subprocess.run(
        ["himalaya"] + args,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print(f"[red]Error running himalaya:[/red] {result.stderr}")
        console.print(f"[red]Command:[/red] himalaya {' '.join(args)}")
        raise typer.Exit(1)

    return result


def get_envelope(message_id: int, folder: str, verbose: bool = False) -> dict | None:
    """Get envelope by ID."""
    result = run_himalaya(
        [
            "envelope",
            "list",
            "--account",
            ACCOUNT,
            "--folder",
            folder,
            "--output",
            "json",
        ],
        verbose=verbose,
    )

    try:
        envelopes = json.loads(result.stdout)
        for envelope in envelopes:
            if str(envelope["id"]) == str(message_id):
                return envelope
        return None
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing JSON:[/red] {e}")
        raise typer.Exit(1)


def get_message_body(message_id: int, folder: str, verbose: bool = False) -> str:
    """Get message body content."""
    result = run_himalaya(
        [
            "message",
            "read",
            "--account",
            ACCOUNT,
            "--folder",
            folder,
            "--preview",
            "--no-headers",
            "--output",
            "json",
            str(message_id),
        ],
        verbose=verbose,
    )

    try:
        body = json.loads(result.stdout)
        return body if isinstance(body, str) else ""
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing JSON:[/red] {e}")
        raise typer.Exit(1)


def sanitize_filename(name: str) -> str:
    """Sanitize filename for Unix filesystems."""
    sanitized = name.replace("/", "-").replace("\\", "-")
    sanitized = sanitized.replace("\x00", "")
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized


def generate_filename(
    message_id: int,
    subject: str,
    date_str: str,
    output_format: str,
    date_prefix: bool = False,
) -> str:
    """Generate filename for the saved email."""
    ext = {
        "markdown": "md",
        "text": "txt",
        "json": "json",
    }[output_format]

    if date_prefix:
        try:
            date_obj = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
            date_prefix_str = date_obj.strftime("%Y-%m-%d")
            sanitized_subject = sanitize_filename(subject)
            return f"{date_prefix_str}-{sanitized_subject}.{ext}"
        except ValueError:
            pass

    return f"{message_id}.{ext}"


def format_markdown(
    envelope: dict, body: str, folder: str, attachments: list[Path] | None = None
) -> str:
    """Format email as Markdown."""
    from_data = envelope.get("from", {})
    from_addr = from_data.get("address", "")
    from_name = from_data.get("name", "")
    from_str = f"{from_name} <{from_addr}>" if from_name else from_addr

    to_data = envelope.get("to", {})
    if isinstance(to_data, dict):
        to_addr = to_data.get("address", "")
        to_name = to_data.get("name", "")
        to_str = f"{to_name} <{to_addr}>" if to_name else to_addr
    elif isinstance(to_data, list):
        to_str = ", ".join(
            [
                f"{t.get('name', '')} <{t.get('address', '')}>"
                if t.get("name")
                else t.get("address", "")
                for t in to_data
            ]
        )
    else:
        to_str = ""

    date_str = envelope.get("date", "")
    subject_str = envelope.get("subject", "")
    message_id = envelope.get("id", "")

    attachments_section = ""
    if attachments:
        attachments_section = "\n\n---\n\n**Attachments:**\n"
        for attachment in attachments:
            attachments_section += f"- `{attachment}`\n"

    return dedent(
        f"""\
        # {subject_str}

        **From:** {from_str}
        **To:** {to_str}
        **Date:** {date_str}
        **Subject:** {subject_str}

        ---

        {body}{attachments_section}

        ---

        *Saved from: {folder} (ID: {message_id})*
        """
    )


def format_text(
    envelope: dict, body: str, folder: str, attachments: list[Path] | None = None
) -> str:
    """Format email as plain text."""
    from_data = envelope.get("from", {})
    from_addr = from_data.get("address", "")
    from_name = from_data.get("name", "")
    from_str = f"{from_name} <{from_addr}>" if from_name else from_addr

    to_data = envelope.get("to", {})
    if isinstance(to_data, dict):
        to_addr = to_data.get("address", "")
        to_name = to_data.get("name", "")
        to_str = f"{to_name} <{to_addr}>" if to_name else to_addr
    elif isinstance(to_data, list):
        to_str = ", ".join(
            [
                f"{t.get('name', '')} <{t.get('address', '')}>"
                if t.get("name")
                else t.get("address", "")
                for t in to_data
            ]
        )
    else:
        to_str = ""

    date_str = envelope.get("date", "")
    subject_str = envelope.get("subject", "")
    message_id = envelope.get("id", "")

    attachments_section = ""
    if attachments:
        attachments_section = "\n\n---\n\nAttachments:\n"
        for attachment in attachments:
            attachments_section += f"  - {attachment}\n"

    return dedent(
        f"""\
        From: {from_str}
        To: {to_str}
        Date: {date_str}
        Subject: {subject_str}

        {body}{attachments_section}

        ---
        Saved from: {folder} (ID: {message_id})
        """
    )


def _download_attachments_internal(
    message_id: int, folder: str, attachment_dir: Path | None, verbose: bool = False
) -> list[Path]:
    """Download attachments from an email message.

    Returns list of downloaded attachment paths.
    """
    result = run_himalaya(
        [
            "attachment",
            "download",
            "--account",
            ACCOUNT,
            "--folder",
            folder,
            str(message_id),
        ],
        verbose=verbose,
    )

    downloaded_files = []
    output_lines = result.stdout + result.stderr
    for line in output_lines.splitlines():
        match = re.search(r'Downloading "(.+?)"…', line)
        if match:
            downloaded_path = Path(match.group(1))
            downloaded_files.append(downloaded_path)
            if verbose:
                console.print(f"[dim]Found attachment:[/dim] {downloaded_path}")

    if attachment_dir and downloaded_files:
        attachment_dir.mkdir(parents=True, exist_ok=True)
        moved_files = []
        for old_path in downloaded_files:
            new_path = attachment_dir / old_path.name
            shutil.move(str(old_path), str(new_path))
            moved_files.append(new_path)
            if verbose:
                console.print(f"[dim]Moved to:[/dim] {new_path}")
        return moved_files

    return downloaded_files


def format_json(envelope: dict, body: str, folder: str) -> str:
    """Format email as JSON (raw from himalaya)."""
    data = {
        "folder": folder,
        "envelope": envelope,
        "body": body,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


@app.command()
def save(
    message_id: int = typer.Argument(..., help="Message ID to save"),
    folder: str = typer.Option("INBOX", "--folder", "-f", help="Folder to search"),
    output: Path = typer.Option(
        None, "--output", "-o", help="Output directory or file path"
    ),
    format: Literal["markdown", "text", "json"] = typer.Option(
        "markdown", "--format", help="Output format (markdown/text/json)"
    ),
    date_prefix: bool = typer.Option(
        False, "--date-prefix", help="Add YYYY-MM-DD prefix to filename"
    ),
    overwrite: bool = typer.Option(
        False, "--overwrite", help="Overwrite existing file without confirmation"
    ),
    download_attachments: bool = typer.Option(
        False, "--download-attachments", help="Download email attachments"
    ),
    attachment_dir: Path | None = typer.Option(
        None, "--attachment-dir", help="Directory for attachments"
    ),
    verbose: bool = typer.Option(
        False, "-v", "--verbose", help="Show himalaya commands"
    ),
):
    """Save an email to a file."""

    console.print(f"[dim]Fetching envelope {message_id} from {folder}...[/dim]")
    envelope = get_envelope(message_id, folder, verbose)

    if not envelope:
        console.print(f"[red]Email with ID {message_id} not found in {folder}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Fetching message body...[/dim]")
    body = get_message_body(message_id, folder, verbose)

    attachments: list[Path] | None = None
    if download_attachments:
        console.print(f"[dim]Downloading attachments...[/dim]")
        attachments = _download_attachments_internal(
            message_id, folder, attachment_dir, verbose
        )
        if attachments:
            console.print(
                f"[green]✓[/green] Downloaded [cyan]{len(attachments)}[/cyan] attachment(s)"
            )
        else:
            console.print("[dim]No attachments found[/dim]")

    console.print(f"[dim]Formatting as {format}...[/dim]")
    if format == "markdown":
        content = format_markdown(envelope, body, folder, attachments)
    elif format == "text":
        content = format_text(envelope, body, folder, attachments)
    else:
        content = format_json(envelope, body, folder)

    subject = envelope.get("subject", "")
    date = envelope["date"]
    filename = generate_filename(message_id, subject, date, format, date_prefix)

    if output:
        if output.is_dir():
            output.mkdir(parents=True, exist_ok=True)
            output_path = output / filename
        elif output.exists():
            output_path = output
        elif not output.suffix:
            output.mkdir(parents=True, exist_ok=True)
            output_path = output / filename
        else:
            output_path = output
            output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        output_path = Path(filename)

    if output_path.exists() and not overwrite:
        console.print(f"[yellow]File already exists:[/yellow] {output_path}")
        if not Confirm.ask("Overwrite?", default=False):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)

    output_path.write_text(content, encoding="utf-8")
    console.print(
        Panel(
            f"[green]✓[/green] Saved to [cyan]{output_path}[/cyan]\n\n"
            f"[dim]Format:[/dim] {format}\n"
            f"[dim]Subject:[/dim] {subject}\n"
            f"[dim]From:[/dim] {envelope['from'].get('address', '')}",
            title="Email Saved",
            border_style="green",
        )
    )


if __name__ == "__main__":
    app()
