#!/usr/bin/env python3
# /// script
# dependencies = [
#   "ruamel.yaml",
#   "zstandard",
#   "pygments",
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
from io import StringIO
from itertools import chain
from os import path
from pathlib import Path
from typing import Any

import zstandard as zstd
from pygments import highlight
from pygments.formatters import TerminalFormatter
from pygments.lexers import YamlLexer
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
from ruamel.yaml.scanner import SimpleKey

DB_PATH = path.expanduser("~/.local/share/zed/threads/threads.db")


def pick(dictionary, pick_keys, discard_keys, ignore_keys=()):
    difference = (set(dictionary) - set(ignore_keys)).symmetric_difference(
        set(pick_keys + discard_keys)
    )
    if difference:
        raise ValueError(
            f"Got keys {set(dictionary)} but trying to pick {pick_keys} and drop {discard_keys}\nin {dictionary}"
        )
    return [value for key, value in dictionary.items() if key in pick_keys]


def simplify_mention(mention_data):
    uri, content = pick(mention_data, ["uri", "content"], [])
    for uri_type, data in uri.items():
        if uri_type == "File":
            path = Path(pick(data, ["abs_path"], [])[0])
            yield f"@{path}"
            yield f"```{path.suffix[1:]}"
            yield content
            yield "```"
        elif uri_type == "Rule":
            (name,) = pick(data, ["name"], ["id"])
            yield f"@{name}"
            yield f"```"
            yield content.strip()
            yield "```"


def simplify_user(user_data):
    (part_data,) = pick(user_data, ["content"], ["id"])
    for element, data in chain.from_iterable(part.items() for part in part_data):
        if element == "Text":
            yield data
        elif element == "Mention":
            yield from simplify_mention(data)
        else:
            yield repr((element, data))


def simplify_agent(agent_data):
    content, tool_results = pick(agent_data, ["content", "tool_results"], [])
    for content_type, content_data in chain.from_iterable(
        part.items() for part in content
    ):
        if content_type == "Thinking":
            (text,) = pick(content_data, ["text"], ["signature"])
            if text.strip():
                yield {content_type: text}
        elif content_type == "Text":
            if content_data.strip():
                yield {"Agent": content_data.strip()}
        elif content_type == "ToolUse":
            name, input = pick(
                content_data,
                ["name", "input"],
                ["id", "raw_input", "is_input_complete"],
            )
            yield {content_type: {"name": name, "input": input}}
        else:
            raise ValueError(f"Unexpected content type: {content_type}")
    for tool_result in tool_results.values():
        tool_name = tool_result["tool_name"]
        if tool_name == "edit_file":
            is_error, content = pick(
                tool_result,
                ["is_error", "content"],
                ["tool_name", "tool_use_id", "output"],
                ["old_text", "diff", "edit_agent_output"],
            )
        elif tool_name == "grep":
            is_error, content = pick(
                tool_result,
                ["is_error", "content"],
                ["tool_name", "tool_use_id", "output"],
            )
        elif tool_name == "read_file":
            is_error, content = pick(
                tool_result,
                ["is_error", "content"],
                ["tool_name", "tool_use_id", "output"],
            )
        else:
            raise ValueError(f"Unexpected tool name: {tool_name}")
        (text,) = pick(content, ["Text"], [])
        yield {"ToolError" if is_error else "ToolResult": text}


def simplify_messages(messages):
    for message in messages:
        if isinstance(message, str):
            yield {"?": message}
        else:
            for role, data in message.items():
                if role == "User":
                    yield {role: "\n".join(simplify_user(data))}
                elif role == "Agent":
                    yield from simplify_agent(data)
                else:
                    yield {role: data}


def simplify_thread_data(thread):
    """
    Simplify thread data for human readability by:
    - Removing unnecessary metadata
    - Extracting key information
    - Restructuring complex nested objects
    """
    return {"messages": list(simplify_messages(thread["messages"]))}


def process_multiline_strings(obj):
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


def read_all_threads(db_path: str = DB_PATH) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
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
        highlighted_yaml = highlight(yaml_content, YamlLexer(), TerminalFormatter())
        sys.stdout.write(highlighted_yaml)
    else:
        # Output plain YAML without highlighting
        sys.stdout.write(yaml_content)


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
