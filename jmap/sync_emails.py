#!/usr/bin/env python3
"""Sync emails from a JMAP server to a local directory tree.

Each email gets its own subfolder:
  <output-dir>/YYYY-MM-DD <Subject>/
    email.md        # headers + plain-text body
    <attachment>    # original filename, downloaded once

Characters illegal in filenames (< > : " / \\ | ? *) are replaced with _.
"""
import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from textwrap import dedent

DEFAULTS = {
    "jmap_url":  "http://127.0.0.1:8895",
    "account_id": "kaihola",
}


def parse_earliest_date_filter(value):
    if value.lower() == "none":
        return "none"
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "must be YYYY-MM-DD or 'none'"
        ) from exc


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-filter", default=None,
                   help="Sender domain or address fragment to filter on (e.g. 'example.com')")
    p.add_argument("--subject-filter", default=None,
                   help="Subject fragment to filter on (e.g. 'gothoni')")
    p.add_argument("--to-filter", default=None,
                   help="Recipient domain or address fragment to filter on (e.g. 'gothoni.com')")
    p.add_argument("--output-dir", required=True, type=Path,
                   help="Directory to write email folders into")
    p.add_argument("--account", default=DEFAULTS["account_id"],
                   help=f"JMAP account ID (default: {DEFAULTS['account_id']})")
    p.add_argument("--jmap-url", default=DEFAULTS["jmap_url"],
                   help=f"JMAP base URL (default: {DEFAULTS['jmap_url']})")
    p.add_argument("--limit", type=int, default=500,
                   help="Max emails to fetch per run (default: 500)")
    p.add_argument("--earliest-date-filter", type=parse_earliest_date_filter,
                   help="Earliest received date (YYYY-MM-DD); use 'none' to disable (default: latest date already in output directory)")
    p.add_argument("--download-missing-attachments", action="store_true",
                   help="Download attachments missing from already-synced emails")
    args = p.parse_args()
    if not args.from_filter and not args.subject_filter and not args.to_filter:
        p.error("at least one of --from-filter, --to-filter, or --subject-filter is required")
    return args


def latest_fetched_date(output_dir):
    """Return the newest message date represented in the output directory."""
    dates = (
        match.group(1)
        for path in output_dir.iterdir()
        if path.is_dir()
        for match in [re.match(r"(\d{4}-\d{2}-\d{2})(?: .*)?$", path.name)]
        if match
    )
    return max(dates, default=None)


def jmap_call(base_url, calls):
    body = json.dumps({
        "using": ["urn:ietf:params:jmap:core", "urn:ietf:params:jmap:mail"],
        "methodCalls": calls,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/jmap", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]', '_', s).strip()


def download_blob(base_url, account_id, blob_id, raw_name, dest):
    if dest.exists():
        print(f"  SKIP  {dest.name}")
        return
    url = (
        f"{base_url}/jmap/download/{account_id}"
        f"/{urllib.parse.quote(blob_id, safe='')}"
        f"/{urllib.parse.quote(raw_name, safe='')}"
    )
    try:
        dest.write_bytes(urllib.request.urlopen(url).read())
        print(f"  DL    {dest.name}")
    except Exception as exc:
        print(f"  ERR   {dest.name} — {exc}")


def main():
    args = parse_args()
    base_url   = args.jmap_url
    account_id = args.account
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    jmap_filter = {}
    if args.earliest_date_filter != "none":
        earliest = args.earliest_date_filter
        if earliest is None:
            last_date = latest_fetched_date(output_dir)
            earliest = date.fromisoformat(last_date) if last_date else None
        if earliest:
            jmap_filter["after"] = f"{earliest.isoformat()}T00:00:00Z"
    if args.from_filter:
        jmap_filter["from"] = args.from_filter
    if args.to_filter:
        jmap_filter["to"] = args.to_filter
    if args.subject_filter:
        jmap_filter["subject"] = args.subject_filter

    resp = jmap_call(base_url, [
        ["Email/query", {
            "accountId": account_id,
            "filter": jmap_filter,
            "sort": [{"property": "receivedAt", "isAscending": True}],
            "limit": args.limit,
        }, "q"],
        ["Email/get", {
            "accountId": account_id,
            "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
            "properties": [
                "subject", "from", "to", "receivedAt",
                "textBody", "htmlBody", "attachments", "bodyValues",
            ],
            "fetchAllBodyValues": True,
        }, "g"],
    ])

    emails = resp["methodResponses"][1][1]["list"]
    emails.sort(key=lambda e: e["receivedAt"])
    filter_desc = ", ".join(f"{k}={v}" for k, v in jmap_filter.items())
    print(f"Found {len(emails)} emails matching '{filter_desc}'")

    for email in emails:
        date    = email["receivedAt"][:10]
        subject = safe_name(email.get("subject") or "(no subject)")[:80]
        folder  = output_dir / f"{date} {subject}"
        folder.mkdir(parents=True, exist_ok=True)

        md_path = folder / "email.md"
        existing_email = md_path.exists()
        if existing_email:
            print(f"SKIP  {folder.name}")
        else:
            from_str = ", ".join(
                f"{p.get('name', '')} <{p.get('email', '')}>"
                for p in (email.get("from") or [])
            )
            to_str = ", ".join(
                f"{p.get('name', '')} <{p.get('email', '')}>"
                for p in (email.get("to") or [])
            ) or "(undisclosed)"
            bv   = email.get("bodyValues", {})
            body = ""
            for part in email.get("textBody", []):
                if part.get("partId") in bv:
                    body = bv[part["partId"]]["value"]
                    break
            if not body:
                for part in email.get("htmlBody", []):
                    if part.get("partId") in bv:
                        body = re.sub(r"<[^>]+>", "", bv[part["partId"]]["value"])
                        break

            md_path.write_text(dedent(f"""\
                # {email.get('subject', '(no subject)')}

                **Date**: {email['receivedAt']}
                **From**: {from_str}
                **To**: {to_str}

                ---

                {body.strip()}
            """), encoding="utf-8")
            print(f"SAVE  {folder.name}")

        if existing_email and not args.download_missing_attachments:
            continue

        for att in (email.get("attachments") or []):
            raw  = att.get("name") or att.get("blobId", "unknown")
            dest = folder / safe_name(urllib.parse.unquote(raw))
            download_blob(base_url, account_id, att["blobId"], raw, dest)

    print("Done.")


if __name__ == "__main__":
    main()
