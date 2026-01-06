#!/usr/bin/env python3
"""Read emails with structured output."""

# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "typer>=0.12.0",
#     "rich>=13.7.0",
#     "html2text>=2024.2.26",
# ]
# ///

import json
import re
import subprocess
from textwrap import dedent
from typing import Literal

import typer
from rich.console import Console
from rich.panel import Panel

import html2text

app = typer.Typer(help="Read emails with structured output")
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


def parse_mime_parts(raw_body: str) -> list[dict]:
    """Parse MIME parts from himalaya's <#part> tags."""
    parts = []
    pattern = r'<#part\s+type=([^>\s]+)(?:\s+filename="([^"]*)")?>(.*?)<#/part>'
    matches = re.findall(pattern, raw_body, re.DOTALL)

    for part_type, filename, content in matches:
        parts.append(
            {
                "type": part_type,
                "filename": filename if filename else None,
                "content": content.strip(),
            }
        )

    return parts


def extract_body_content(
    parts: list[dict], prefer_text: bool = True, preserve_html: bool = False
) -> str:
    """Extract body content from MIME parts."""
    text_plain_part = None
    text_html_part = None

    for part in parts:
        if part["type"] == "text/plain":
            text_plain_part = part
        elif part["type"] == "text/html":
            text_html_part = part

    if text_plain_part:
        return text_plain_part["content"]
    elif text_html_part and not preserve_html:
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0
        return h.handle(text_html_part["content"])
    elif text_html_part:
        return text_html_part["content"]
    else:
        return ""


def format_text_output(envelope: dict, body: str, folder: str) -> str:
    """Format email as plain text with rich panel."""
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

    content = dedent(
        f"""\
        From: {from_str}
        To: {to_str}
        Date: {date_str}
        Subject: {subject_str}

        {body}

        ---
        Folder: {folder} (ID: {message_id})
        """
    )
    return content


def format_markdown_output(envelope: dict, body: str, folder: str) -> str:
    """Format email as Markdown without panel borders."""
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

    content = dedent(
        f"""\
        # {subject_str}

        **From:** {from_str}
        **To:** {to_str}
        **Date:** {date_str}
        **Subject:** {subject_str}

        ---

        {body}

        ---

        *Folder: {folder} (ID: {message_id})*
        """
    )
    return content


def format_json_output(
    envelope: dict, parts: list[dict], folder: str, preserve_html: bool
) -> str:
    """Format email as JSON with full MIME structure."""
    data = {
        "folder": folder,
        "envelope": envelope,
        "mime_parts": parts,
        "preserve_html": preserve_html,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def format_raw_output(raw_body: str) -> str:
    """Format email as raw himalaya output."""
    return raw_body


@app.command()
def read(
    message_id: int = typer.Argument(..., help="Message ID to read"),
    folder: str = typer.Option("INBOX", "--folder", "-f", help="Folder to search"),
    output_format: Literal["text", "markdown", "json", "raw"] = typer.Option(
        "text", "--format", help="Output format"
    ),
    preserve_html: bool = typer.Option(
        False, "--preserve-html", help="Keep HTML content (for json/raw formats)"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Show parsing details"),
):
    """Read an email with structured output."""

    console.print(f"[dim]Fetching envelope {message_id} from {folder}...[/dim]")
    envelope = get_envelope(message_id, folder, verbose)

    if not envelope:
        console.print(f"[red]Email with ID {message_id} not found in {folder}[/red]")
        raise typer.Exit(1)

    console.print(f"[dim]Fetching message body...[/dim]")
    body_result = run_himalaya(
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
        raw_body = json.loads(body_result.stdout)
        if not isinstance(raw_body, str):
            console.print("[yellow]Message body is empty or invalid format[/yellow]")
            raise typer.Exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error parsing JSON:[/red] {e}")
        raise typer.Exit(1)

    parts = parse_mime_parts(raw_body)

    if verbose:
        console.print(f"[dim]Found {len(parts)} MIME part(s):[/dim]")
        for part in parts:
            if part["filename"]:
                console.print(
                    f"  [dim]- {part['type']} (file: {part['filename']})[/dim]"
                )
            else:
                console.print(f"  [dim]- {part['type']}[/dim]")

    if output_format == "raw":
        content = format_raw_output(raw_body)
        console.print(content)
    elif output_format == "json":
        content = format_json_output(envelope, parts, folder, preserve_html)
        console.print(content)
    else:
        body = extract_body_content(parts, prefer_text=True, preserve_html=False)

        if output_format == "text":
            content = format_text_output(envelope, body, folder)
        elif output_format == "markdown":
            content = format_markdown_output(envelope, body, folder)
        else:
            console.print(f"[red]Invalid format: {output_format}[/red]")
            raise typer.Exit(1)

        console.print(
            Panel(
                content,
                title=f"[bold]{envelope.get('subject', '(no subject)')}[/bold]",
                border_style="blue",
            )
        )


if __name__ == "__main__":
    app()
