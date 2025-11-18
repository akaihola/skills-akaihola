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
# Recommended usage (with uv):
#   uv run read_zed_threads.py          # Output the first thread
#   uv run read_zed_threads.py 5        # Output the thread at index 5
#
# Note: Use `uv run` to automatically handle dependencies defined in the script metadata

import base64
import json
import sqlite3
import sys
from os import path
from typing import Any

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


def extract_text_from_segment(seg: Any) -> str:
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
                    pieces.append(raw)
                else:
                    pieces.append(json.dumps(raw, ensure_ascii=False))
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


def message_to_role_and_text(msg: Any) -> dict[str, str]:
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
    for seg in segments:
        t = extract_text_from_segment(seg)
        parts.append(t)
    content = "\n".join(parts).strip()
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


def thread_to_lm_context(thread_obj: dict[str, Any]) -> list[dict[str, str]]:
    msgs = thread_obj.get("messages", [])
    context = []
    title = thread_obj.get("title") or thread_obj.get("summary") or ""
    if title:
        context.append({"role": "system", "content": f"Thread title: {title}"})
    for m in msgs:
        item = message_to_role_and_text(m)
        if item["content"]:
            context.append(item)
    return context


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
        # Use LiteralScalarString and strip trailing newline to encourage '|-' chomping indicator
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
    if len(sys.argv) > 1:
        idx = int(sys.argv[1])
    if idx < 0 or idx >= len(threads):
        print(f"index out of range (0..{len(threads)-1})")
        sys.exit(2)
    make_yaml_output(threads[idx])
