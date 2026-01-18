#!/usr/bin/env -S uv run
# SPDX-License-Identifier: MIT

"""Save emails to files in various formats."""

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
# ]
# ///

import json
import re
import shutil
import subprocess  # noqa: S404
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from textwrap import dedent
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm

app = typer.Typer(help="Save emails to files in various formats")
console = Console()

ACCOUNT = "akaihola"


def run_himalaya(
    args: list[str], *, verbose: bool = False
) -> subprocess.CompletedProcess:
    """Run a himalaya command and return result."""
    if verbose:
        console.print(f"[dim]Running: himalaya {' '.join(args)}[/dim]")

    himalaya_path = shutil.which("himalaya")
    if not himalaya_path:
        console.print("[red]Error:[/red] himalaya command not found in PATH")
        raise typer.Exit(1)

    result = subprocess.run(  # noqa: S603
        [himalaya_path, *args],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )

    if result.returncode != 0:
        console.print(f"[red]Error running himalaya:[/red] {result.stderr}")
        console.print(f"[red]Command:[/red] himalaya {' '.join(args)}")
        raise typer.Exit(1)

    return result


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


def get_envelope_date(
    message_id: int, folder: str, from_address: str = "", *, verbose: bool = False
) -> str:
    """Fetch envelope date from himalaya envelope list by searching.

    Searches envelopes by sender address and finds the one matching the message ID.
    Returns date string in ISO 8601 format if found, empty string otherwise.
    """
    if not from_address:
        return ""

    try:
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
                f"from {from_address}",
            ],
            verbose=verbose,
        )

        envelopes = json.loads(result.stdout)
        if isinstance(envelopes, list):
            for envelope in envelopes:
                if envelope.get("id") == str(message_id) and "date" in envelope:
                    return envelope["date"]
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    except SystemExit:
        pass

    return ""


def parse_email_address(address: str) -> dict:
    """Parse a single email address into name and address components."""
    match = re.match(r"^(.*?)\s*<([^>]+)>$", address)
    if match:
        return {
            "name": match.group(1).strip(),
            "address": match.group(2).strip(),
        }
    if "<" in address and ">" in address:
        email = re.search(r"<([^>]+)>", address)
        if email:
            return {"address": email.group(1)}
    return {"address": address}


def parse_to_addresses(to_header: str) -> dict | list:
    """Parse To header into single address dict or list of dicts."""
    to_addrs = [addr.strip() for addr in to_header.split(",")]
    if len(to_addrs) == 1:
        return parse_email_address(to_addrs[0])
    return [parse_email_address(addr) for addr in to_addrs]


def extract_message_body(message_text: str) -> str:
    """Extract body from message text by finding headers separator."""
    headers_end = message_text.find("\n\n")
    if headers_end == -1:
        headers_end = message_text.find("\n---\n")
    return message_text[headers_end + 2 :].strip() if headers_end > 0 else message_text


def get_message(message_id: int, folder: str, *, verbose: bool = False) -> dict:
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
            message_text = ""

        headers = parse_email_headers(message_text)
        body = extract_message_body(message_text)

        envelope = {
            "id": str(message_id),
            "from": {},
            "to": {},
            "date": "",
            "subject": "",
        }

        if "from" in headers:
            envelope["from"] = parse_email_address(headers["from"])

        if "to" in headers:
            envelope["to"] = parse_to_addresses(headers["to"])

        envelope["date"] = headers.get("date", "")
        if not envelope["date"]:
            from_addr = envelope.get("from", {}).get("address", "")
            envelope["date"] = get_envelope_date(
                message_id, folder, from_addr, verbose=verbose
            )

        envelope["subject"] = headers.get("subject", "")

        return {"envelope": envelope, "body": body}

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
    *,
    date_prefix: bool = False,
) -> str:
    """Generate filename for the saved email."""
    ext = {
        "markdown": "md",
        "text": "txt",
        "json": "json",
    }[output_format]

    if date_prefix and date_str:
        date_formats = [
            "%Y-%m-%d %H:%M%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ]

        for date_format in date_formats:
            try:
                date_obj = datetime.strptime(date_str, date_format)
                date_obj = date_obj.astimezone()
                date_prefix_str = date_obj.strftime("%Y-%m-%d")
                sanitized_subject = sanitize_filename(subject)
                return f"{date_prefix_str}-{sanitized_subject}.{ext}"
            except ValueError:
                continue

        try:
            date_obj = parsedate_to_datetime(date_str)
            date_obj = date_obj.astimezone()
            date_prefix_str = date_obj.strftime("%Y-%m-%d")
            sanitized_subject = sanitize_filename(subject)
            return f"{date_prefix_str}-{sanitized_subject}.{ext}"
        except (TypeError, ValueError):
            pass

        console.print(
            f"[yellow]⚠[/yellow] Could not parse date: [dim]{date_str}[/dim]\n"
            f"[yellow]⚠[/yellow] Falling back to message ID in filename"
        )

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


def fix_attachment_paths_in_body(
    body: str,
    downloaded_files: list[Path],
    email_output_dir: Path,
    *,
    verbose: bool = False,
) -> str:
    """Replace himalaya's default download paths with correct relative paths.

    This fixes a known issue where himalaya's message read output contains
    <#part filename="..."> tags with paths based on the configured downloads-dir,
    not where we actually download/move the attachments.

    Args:
        body: Message body containing <#part> tags with incorrect paths
        downloaded_files: List of actual attachment paths after download/move
        email_output_dir: Directory where the email file will be saved
        verbose: Print debug info about path replacements

    Returns:
        Body with corrected relative paths in <#part> tags

    """
    if not downloaded_files:
        return body

    filename_to_relative_path = {}
    for attachment_path in downloaded_files:
        try:
            relative_path = attachment_path.relative_to(email_output_dir)
            filename_to_relative_path[attachment_path.name] = str(relative_path)
            if verbose:
                console.print(
                    f"[dim]Path mapping: {attachment_path.name} → {relative_path}[/dim]"
                )
        except ValueError:
            filename_to_relative_path[attachment_path.name] = str(attachment_path)
            if verbose:
                console.print(
                    f"[dim]Path mapping (absolute): {attachment_path.name}"
                    f" → {attachment_path}[/dim]"
                )

    replacement_count = 0

    def replace_path(match: re.Match) -> str:
        nonlocal replacement_count
        part_type = match.group(1)
        old_path = match.group(2)
        if old_path:
            filename = Path(old_path).name
            if filename in filename_to_relative_path:
                replacement_count += 1
                new_path = filename_to_relative_path[filename]
                return f'<#part type={part_type} filename="{new_path}"><#/part>'
        return match.group(0)

    pattern = r'<#part\s+type=([^>\s]+)\s+filename="([^"]+)"><#/part>'
    updated_body = re.sub(pattern, replace_path, body)

    if verbose and replacement_count > 0:
        console.print(f"[dim]Fixed {replacement_count} attachment path(s)[/dim]")

    return updated_body


def _download_attachments_internal(
    message_id: int, folder: str, attachment_dir: Path | None, *, verbose: bool = False
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


# ruff: disable[FBT002]
@app.command()
def save(
    message_id: Annotated[int, typer.Argument(..., help="Message ID to save")],
    folder: Annotated[
        str, typer.Option("--folder", "-f", help="Folder to search")
    ] = "INBOX",
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output directory or file path"),
    ] = None,
    format: Annotated[
        Literal["markdown", "text", "json"],
        typer.Option(help="Output format (markdown/text/json)"),
    ] = "markdown",
    overwrite: Annotated[
        bool,
        typer.Option(help="Overwrite existing file without confirmation"),
    ] = False,
    download_attachments: Annotated[
        bool,
        typer.Option(
            help=(
                "Download email attachments "
                "(default: enabled, use --no-download-attachments to skip)"
            ),
        ),
    ] = True,
    attachment_dir: Annotated[
        Path | None,
        typer.Option(help="Directory for attachments"),
    ] = None,
    date_prefix: Annotated[
        bool,
        typer.Option(help="Prefix filename with date"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show himalaya commands"),
    ] = False,
) -> None:
    """Save an email to a file."""
    console.print(f"[dim]Fetching message {message_id} from {folder}...[/dim]")
    message_data = get_message(message_id, folder, verbose=verbose)

    envelope = message_data["envelope"]
    body = message_data["body"]

    subject = envelope.get("subject", "")
    date = envelope["date"]
    filename = generate_filename(
        message_id, subject, date, format, date_prefix=date_prefix
    )

    # Determine output_path first, before downloading attachments
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

    # Ensure output directory exists before downloading
    output_path.parent.mkdir(parents=True, exist_ok=True)

    attachments: list[Path] | None = None
    if download_attachments:
        console.print("[dim]Downloading attachments...[/dim]")
        effective_attachment_dir = attachment_dir or output_path.parent
        attachments = _download_attachments_internal(
            message_id, folder, effective_attachment_dir, verbose=verbose
        )
        if attachments:
            console.print(
                f"[green]✓[/green] Downloaded [cyan]{len(attachments)}[/cyan] attachment(s)"
            )
        else:
            console.print("[dim]No attachments found[/dim]")

    if attachments:
        email_output_dir = output_path.parent
        body = fix_attachment_paths_in_body(
            body, attachments, email_output_dir, verbose=verbose
        )

    console.print(f"[dim]Formatting as {format}...[/dim]")
    if format == "markdown":
        content = format_markdown(envelope, body, folder, attachments)
    elif format == "text":
        content = format_text(envelope, body, folder, attachments)
    else:
        content = format_json(envelope, body, folder)

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


# ruff: enable[FBT002]


if __name__ == "__main__":
    app()
