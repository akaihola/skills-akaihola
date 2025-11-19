#!/usr/bin/env python3
# /// script
# dependencies = [
#   "ruamel.yaml",
#   "zstandard",
#   "pygments",
#   "pydantic",
# ]
# ///
# Simplified script: read zed threads.db, output raw thread JSON as YAML
#
# IMPORTANT: Always use `uv run` to execute this script to ensure dependencies are properly installed:
#   uv run read_zed_threads.py          # Output the first thread
#   uv run read_zed_threads.py 5        # Output the thread at index 5
#   uv run read_zed_threads.py --no-color  # Output without syntax highlighting
#
# Note: This script requires uv to handle dependencies defined in the script metadata

import json
import sqlite3
import sys
from collections.abc import Generator
from io import StringIO
from pathlib import Path
from typing import Any, Literal

import zstandard as zstd
from pydantic import BaseModel, ConfigDict
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import YamlLexer
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

DB_PATH = Path.home() / ".local/share/zed/threads/threads.db"


# --- Pydantic Models for Schema Validation ---


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileUri(StrictModel):
    abs_path: str


class RuleUri(StrictModel):
    name: str
    id: str


class MentionUri(StrictModel):
    File: FileUri | None = None
    Rule: RuleUri | None = None


class MentionData(StrictModel):
    uri: MentionUri
    content: str


class UserContentPart(StrictModel):
    Text: str | None = None
    Mention: MentionData | None = None


class User(StrictModel):
    content: list[UserContentPart]
    id: str


class ThinkingData(StrictModel):
    text: str
    signature: object


class ToolUseData(StrictModel):
    name: str
    input: object
    id: str
    raw_input: object
    is_input_complete: bool


class AgentContentPart(StrictModel):
    Thinking: ThinkingData | None = None
    Text: str | None = None
    ToolUse: ToolUseData | None = None


class TextContent(StrictModel):
    Text: str


class BaseToolResult(StrictModel):
    is_error: bool
    content: TextContent
    tool_use_id: str
    output: object


class EditFileResult(BaseToolResult):
    tool_name: Literal["edit_file"]
    old_text: str | None = None
    diff: str | None = None
    edit_agent_output: object = None


class GrepResult(BaseToolResult):
    tool_name: Literal["grep"]


class ReadFileResult(BaseToolResult):
    tool_name: Literal["read_file"]


class GenericToolResult(BaseToolResult):
    tool_name: str


class Agent(StrictModel):
    content: list[AgentContentPart]
    tool_results: dict[
        str, EditFileResult | GrepResult | ReadFileResult | GenericToolResult
    ]


# --- Simplification Logic ---


def simplify_mention(mention: MentionData) -> Generator[str, None, None]:
    if mention.uri.File:
        path = Path(mention.uri.File.abs_path)
        yield f"@{path}"
        yield f"```{path.suffix[1:]}"
        yield mention.content
        yield "```"
    elif mention.uri.Rule:
        yield f"@{mention.uri.Rule.name}"
        yield "```"
        yield mention.content.strip()
        yield "```"


def simplify_user(user: User) -> Generator[str, None, None]:
    for part in user.content:
        if part.Text is not None:
            yield part.Text
        if part.Mention is not None:
            yield from simplify_mention(part.Mention)


def simplify_agent(agent: Agent) -> Generator[dict[str, Any], None, None]:
    for part in agent.content:
        if part.Thinking:
            if part.Thinking.text.strip():
                yield {"Thinking": part.Thinking.text}
        if part.Text is not None:
            if part.Text.strip():
                yield {"Agent": part.Text.strip()}
        if part.ToolUse:
            tool_use = part.ToolUse
            tool_item = {
                "Tool": {
                    "name": tool_use.name,
                    "input": tool_use.input,
                }
            }
            if tool_use.id in agent.tool_results:
                result = agent.tool_results[tool_use.id]
                result_key = "error" if result.is_error else "result"
                tool_item["Tool"][result_key] = result.content.Text
            yield tool_item


def simplify_messages(messages: list[Any]) -> Generator[dict[str, Any], None, None]:
    for message in messages:
        if isinstance(message, str):
            yield {"?": message}
        elif isinstance(message, dict):
            for role, data in message.items():
                if role == "User":
                    user = User(**data)
                    yield {role: "\n".join(simplify_user(user))}
                elif role == "Agent":
                    agent = Agent(**data)
                    yield from simplify_agent(agent)
                else:
                    yield {role: data}


def simplify_thread_data(thread: dict[str, Any]) -> dict[str, Any]:
    """
    Simplify thread data for human readability by:
    - Removing unnecessary metadata
    - Extracting key information
    - Restructuring complex nested objects
    """
    return {"messages": list(simplify_messages(thread["messages"]))}


def process_multiline_strings(obj: Any) -> Any:
    """
    Recursively process a data structure to format strings containing newlines
    using the |- block scalar format.
    """
    if isinstance(obj, dict):
        return {k: process_multiline_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [process_multiline_strings(item) for item in obj]
    elif isinstance(obj, str) and "\n" in obj:
        # Convert to LiteralScalarString which will be rendered with |-
        return LiteralScalarString(obj)
    else:
        return obj


def decompress_if_needed(data_type: str, blob: bytes) -> bytes:
    # Handle the case where blob is bytes
    if data_type == "zstd":
        # zstd decompression with max_output_size
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(blob, max_output_size=50 * 1024 * 1024)
    return blob


def parse_thread_json(raw_json: bytes) -> dict[str, Any]:
    obj = json.loads(raw_json)
    # saved shape: { "thread": <DbThread>, "version": "0.x" } or direct DbThread
    if isinstance(obj, dict) and "thread" in obj:
        return obj["thread"]
    return obj


def read_all_threads(db_path: str | Path = DB_PATH) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT id, summary, updated_at, data_type, data FROM threads ORDER BY updated_at DESC"
    ).fetchall()
    print(f"Found {len(rows)} rows in database", file=sys.stderr)
    results = []
    for id_, summary, updated_at, data_type, data_blob in rows:
        raw = decompress_if_needed(data_type, data_blob)
        thread = parse_thread_json(raw)
        results.append(
            {"id": id_, "summary": summary, "updated_at": updated_at, "thread": thread}
        )
    print(f"Successfully parsed {len(results)} threads", file=sys.stderr)
    conn.close()
    return results


def make_yaml_output(thread_row: dict[str, Any], use_highlighting: bool = True) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    # First simplify the thread data for human readability
    simplified_thread = simplify_thread_data(thread_row["thread"])

    # Then process the simplified data to handle multiline strings
    processed_thread = process_multiline_strings(simplified_thread)

    # Convert YAML to string first
    yaml_str = StringIO()
    yaml.dump(processed_thread, yaml_str)
    yaml_content = yaml_str.getvalue()

    if use_highlighting:
        # Apply syntax highlighting and output
        _ = sys.stdout.write(highlight(yaml_content, YamlLexer(), TerminalFormatter()))
    else:
        # Output plain YAML without highlighting
        _ = sys.stdout.write(yaml_content)


if __name__ == "__main__":
    threads = read_all_threads()
    if not threads:
        print("No valid threads found", file=sys.stderr)
        print("[]", file=sys.stdout)
        sys.exit(0)

    # default: output YAML for the first thread; optionally pass an index as first arg
    idx = 0
    use_highlighting = True

    # Parse command line arguments
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.isdigit():
            idx = int(arg)
        elif arg == "--no-color":
            use_highlighting = False
        i += 1

    if idx < 0 or idx >= len(threads):
        print(f"index out of range (0..{len(threads)-1})")
        sys.exit(2)

    make_yaml_output(threads[idx], use_highlighting)
