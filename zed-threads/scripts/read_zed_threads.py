#!/usr/bin/env python3
# /// script
# dependencies = [
#   "ruamel.yaml",
#   "zstandard",
# ]
# ///
# Simplified script: read zed threads.db, output raw thread JSON as YAML
#
# IMPORTANT: Always use `uv run` to execute this script to ensure dependencies are properly installed:
#   uv run read_zed_threads.py          # Output the first thread
#   uv run read_zed_threads.py 5        # Output the thread at index 5
#
# Note: This script requires uv to handle dependencies defined in the script metadata

import json
import sqlite3
import sys
from os import path

import zstandard as zstd
from ruamel.yaml import YAML

DB_PATH = path.expanduser("~/.local/share/zed/threads/threads.db")


def decompress_if_needed(data_type: str, blob: bytes) -> bytes:
    # Handle the case where blob is bytes
    if data_type == "zstd":
        # zstd decompression with max_output_size
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(blob, max_output_size=50 * 1024 * 1024)
    return blob


def parse_thread_json(raw_json: bytes) -> dict[str, any]:
    obj = json.loads(raw_json)
    # saved shape: { "thread": <DbThread>, "version": "0.x" } or direct DbThread
    if isinstance(obj, dict) and "thread" in obj:
        return obj["thread"]
    return obj


def read_all_threads(db_path: str = DB_PATH) -> list[dict[str, any]]:
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


def make_yaml_output(thread_row: dict[str, any]) -> None:
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    # Output the raw thread JSON as YAML
    yaml.dump(thread_row["thread"], sys.stdout)


if __name__ == "__main__":
    threads = read_all_threads()
    if not threads:
        print("No valid threads found", file=sys.stderr)
        print("[]", file=sys.stdout)
        sys.exit(0)

    # default: output YAML for the first thread; optionally pass an index as first arg
    idx = 0

    # Parse command line arguments
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg.isdigit():
            idx = int(arg)
        i += 1

    if idx < 0 or idx >= len(threads):
        print(f"index out of range (0..{len(threads)-1})")
        sys.exit(2)

    make_yaml_output(threads[idx])
