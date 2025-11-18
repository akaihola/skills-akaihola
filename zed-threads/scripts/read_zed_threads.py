#!/usr/bin/env python3
# /// script
# dependencies = [
#   "ruamel.yaml",
#   "zstandard",
# ]
# ///
# Minimal script: read zed threads.db, convert to simple LM context, output YAML using ruamel.yaml
# Produces `content:` as a literal block with `|-` (by removing trailing newline and using LiteralScalarString)
#
# IMPORTANT: Always use `uv run` to execute this script to ensure dependencies are properly installed:
#   uv run read_zed_threads.py          # Output the first thread
#   uv run read_zed_threads.py 5        # Output the thread at index 5
#   uv run read_zed_threads.py 5 --raw  # Output raw JSON for the thread at index 5
#
# Note: This script requires uv to handle dependencies defined in the script metadata

import base64
import json
import sqlite3
import sys
from os import path
from typing import Any, Dict, List, Union

import zstandard as zstd
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

DB_PATH = path.expanduser("~/.local/share/zed/threads/threads.db")


def decompress_if_needed(data_type: str, blob) -> bytes:
    # Handle the case where blob is a string (from the database)
    if isinstance(blob, str):
        # The data is a JSON string with a base64-encoded value inside
        # Parse the JSON string
        parsed = json.loads(blob)
        # Extract the base64-encoded data
        data_obj = parsed[0]["data"]
        # Decode the base64-encoded data
        encoded = data_obj["encoded"]
        decoded = base64.b64decode(encoded)
        # zstd decompression with max_output_size
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(decoded, max_output_size=50 * 1024 * 1024)
    elif isinstance(blob, bytes):
        # Handle the case where blob is already bytes
        if data_type == "zstd":
            # zstd decompression with max_output_size
            dctx = zstd.ZstdDecompressor()
            return dctx.decompress(blob, max_output_size=50 * 1024 * 1024)
        return blob
    return blob


def is_valid_json(s: str) -> bool:
    """Check if a string is valid JSON."""
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False


def extract_text_from_segment(seg: Any) -> Union[str, Dict[str, Any]]:
    if isinstance(seg, str):
        return seg
    if isinstance(seg, dict):
        # serde enum shapes: {"Text": "..."} or {"Thinking": {"text": "...", ...}}
        if "Text" in seg:
            return seg["Text"]
        if "text" in seg and isinstance(seg["text"], str):
            return seg["text"]
        if "Thinking" in seg:
            inner = seg["Thinking"]
            if isinstance(inner, dict) and "text" in inner:
                return inner["text"]
        # Tool-like shapes
        inner = seg.get("ToolUse") or seg.get("tool_use") or seg.get("tool") or seg
        if isinstance(inner, dict):
            name = inner.get("name") or inner.get("tool_name")
            raw = inner.get("raw_input") or inner.get("input")
            pieces = []
            if name:
                pieces.append(f"[tool:{name}]")
            if raw is not None:
                if isinstance(raw, str):
                    # Try to parse as JSON first
                    try:
                        parsed = json.loads(raw)
                        # Return the parsed JSON object for better YAML rendering
                        return {"tool": name, "input": parsed}
                    except json.JSONDecodeError:
                        pieces.append(raw)
                elif isinstance(raw, dict):
                    # Return the dict for better YAML rendering
                    return {"tool": name, "input": raw}
                else:
                    pieces.append(json.dumps(raw, ensure_ascii=False))

            # Also check the input field (some tools use this instead of raw_input)
            input_field = inner.get("input")
            if input_field is not None:
                if isinstance(input_field, str):
                    # Try to parse as JSON first
                    try:
                        parsed = json.loads(input_field)
                        # Return the parsed JSON object for better YAML rendering
                        return {"tool": name, "input": parsed}
                    except json.JSONDecodeError:
                        pieces.append(input_field)
                elif isinstance(input_field, dict):
                    # Return the dict for better YAML rendering
                    return {"tool": name, "input": input_field}
                else:
                    pieces.append(json.dumps(input_field, ensure_ascii=False))
            if pieces:
                return " ".join(pieces)

        # Handle tool results
        tool_result = (
            seg.get("ToolResult") or seg.get("tool_result") or seg.get("result")
        )
        if isinstance(tool_result, dict):
            name = tool_result.get("name") or tool_result.get("tool_name")
            result = (
                tool_result.get("result")
                or tool_result.get("output")
                or tool_result.get("content")
            )
            pieces = []
            if name:
                pieces.append(f"[tool_result:{name}]")
            if result is not None:
                if isinstance(result, str):
                    # Try to parse as JSON first
                    try:
                        parsed = json.loads(result)
                        # Return the parsed JSON object for better YAML rendering
                        return {"tool_result": name, "output": parsed}
                    except json.JSONDecodeError:
                        pieces.append(result)
                elif isinstance(result, dict):
                    # Return the dict for better YAML rendering
                    return {"tool_result": name, "output": result}
                else:
                    pieces.append(json.dumps(result, ensure_ascii=False))
            if pieces:
                return " ".join(pieces)
        # Handle file mentions
        if "Mention" in seg and isinstance(seg["Mention"], dict):
            mention = seg["Mention"]
            if (
                "uri" in mention
                and isinstance(mention["uri"], dict)
                and "File" in mention["uri"]
            ):
                file_info = mention["uri"]["File"]
                if "abs_path" in file_info:
                    return f"@{file_info['abs_path']}"
        # join string-valued fields
        parts = []
        for v in seg.values():
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, dict) and "text" in v:
                parts.append(v["text"])
        return " ".join(parts)
    return ""


def message_to_role_and_text(msg: Any) -> dict[str, Union[str, List[Dict[str, Any]]]]:
    role = "assistant"
    payload = msg
    if isinstance(msg, dict) and len(msg) == 1:
        key = next(iter(msg))
        payload = msg[key]
        k = key.lower()
        if k.startswith("user"):
            role = "user"
        elif k.startswith("assistant") or k.startswith("agent"):
            role = "assistant"
        elif k.startswith("system"):
            role = "system"
    elif isinstance(msg, dict) and "role" in msg:
        role = msg.get("role", "assistant").lower()
        payload = msg

    segments = None
    if isinstance(payload, dict):
        segments = payload.get("content") or payload.get("segments")
    if not segments:
        if isinstance(payload, dict) and "text" in payload:
            return {"role": role, "content": payload["text"]}
        return {"role": role, "content": ""}

    parts = []
    structured_parts = []  # For JSON objects that should be rendered as YAML
    for seg in segments:
        t = extract_text_from_segment(seg)
        if isinstance(t, dict):
            # This is a structured tool call or result that should be rendered as YAML
            structured_parts.append(t)
        else:
            parts.append(t)

    # Extract tool results if they exist
    if isinstance(payload, dict) and "tool_results" in payload:
        tool_results = payload["tool_results"]
        if isinstance(tool_results, dict):
            for tool_id, result in tool_results.items():
                if isinstance(result, dict):
                    tool_name = result.get("tool_name") or result.get("tool_name")
                    result_content = (
                        result.get("content")
                        or result.get("output")
                        or result.get("result")
                    )
                    if tool_name and result_content:
                        if (
                            isinstance(result_content, dict)
                            and "Text" in result_content
                        ):
                            result_text = result_content["Text"]
                            parts.append(f"[tool_result:{tool_name}] {result_text}")
                        elif isinstance(result_content, str):
                            # Try to parse as JSON first
                            try:
                                parsed = json.loads(result_content)
                                structured_parts.append(
                                    {"tool_result": tool_name, "output": parsed}
                                )
                            except json.JSONDecodeError:
                                parts.append(
                                    f"[tool_result:{tool_name}] {result_content}"
                                )
                        else:
                            structured_parts.append(
                                {"tool_result": tool_name, "output": result_content}
                            )

    # Combine text parts and structured parts
    content = "\n".join(parts).strip()

    # If we have structured parts, return them along with the text content
    if structured_parts:
        return {"role": role, "content": content, "structured": structured_parts}
    else:
        return {"role": role, "content": content}


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


def thread_to_lm_context(thread_obj: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = thread_obj.get("messages", [])
    context = []
    title = thread_obj.get("title") or thread_obj.get("summary") or ""
    if title:
        context.append({"role": "system", "content": f"Thread title: {title}"})
    for m in msgs:
        item = message_to_role_and_text(m)
        # Include all messages, even those with empty content
        # This ensures messages following tool calls are preserved
        context.append(item)
    return context


def make_raw_json_output(thread_row: dict[str, Any]) -> None:
    """Output the raw thread JSON for debugging purposes"""
    json.dump(thread_row["thread"], sys.stdout, indent=2)

def make_yaml_output(thread_row: dict[str, Any]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    out = {
        "id": thread_row["id"],
        "summary": thread_row["summary"],
        "updated_at": thread_row["updated_at"],
        "context": [],
    }
    ctx = thread_to_lm_context(thread_row["thread"])
    for m in ctx:
        # Check if the message has structured parts (tool calls/results)
        if "structured" in m and m["structured"]:
            # Create a message with both text content and structured parts
            text = m["content"]
            if text.endswith("\n"):
                text_for_yaml = text.rstrip("\n")
            else:
                text_for_yaml = text

            message = {
                "role": m["role"],
                "content": LiteralScalarString(text_for_yaml),
                "structured": m["structured"],  # These will be rendered as YAML
            }
            out["context"].append(message)
        else:
            # Regular text message
            text = m["content"]
            # ensure internal newlines preserved; remove one final trailing newline so ruamel emits '|-'
            if text.endswith("\n"):
                text_for_yaml = text.rstrip("\n")
            else:
                text_for_yaml = text
            out["context"].append(
                {"role": m["role"], "content": LiteralScalarString(text_for_yaml)}
            )
    yaml.dump(out, stream=sys.stdout)


if __name__ == "__main__":
    threads = read_all_threads()
    if not threads:
        print("No valid threads found", file=sys.stderr)
        print("[]", file=sys.stdout)
        sys.exit(0)
    # default: output YAML for the first thread; optionally pass an index as first arg
    idx = 0
    raw_json = False

    # Parse command line arguments
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--raw":
            raw_json = True
        elif arg.isdigit():
            idx = int(arg)
        i += 1

    if idx < 0 or idx >= len(threads):
        print(f"index out of range (0..{len(threads)-1})")
        sys.exit(2)

    if raw_json:
        make_raw_json_output(threads[idx])
    else:
        make_yaml_output(threads[idx])
