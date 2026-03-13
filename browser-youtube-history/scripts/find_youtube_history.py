#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = ["playwright==1.57.0"]
# ///

"""Dump visible YouTube watch history from a logged-in browser CDP session."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from textwrap import dedent

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

DEFAULT_OUTPUT = Path.home() / ".cache" / "browser-youtube-history" / "history-dump.txt"
NO_CONTEXTS_MESSAGE = dedent(
    """
    No browser contexts found on the CDP endpoint.
    Make sure the target Chromium session is already open and logged in.
    """
).strip()


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Dump visible YouTube watch history text from a logged-in "
            "browser CDP session."
        )
    )
    parser.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="Chrome DevTools Protocol HTTP endpoint (default: http://127.0.0.1:9222)",
    )
    parser.add_argument(
        "--history-url",
        default="https://myactivity.google.com/product/youtube?hl=en",
        help="YouTube history URL to open in the logged-in browser",
    )
    parser.add_argument(
        "--scrolls",
        type=int,
        default=4,
        help="Number of downward scroll steps to load more history entries",
    )
    parser.add_argument(
        "--scroll-px",
        type=int,
        default=2500,
        help="Pixels to scroll per step",
    )
    parser.add_argument(
        "--wait-ms",
        type=int,
        default=1000,
        help="Wait after each scroll step in milliseconds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the visible history text dump",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=None,
        help="Optional path for JSON metadata about the session",
    )
    return parser.parse_args()


def connect_browser(cdp_url: str) -> tuple[Playwright, Browser]:
    """Connect to Chromium over CDP.

    Raises:
        RuntimeError: If no browser contexts are available on the endpoint.

    """
    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(cdp_url)
    if not browser.contexts:
        browser.close()
        playwright.stop()
        raise RuntimeError(NO_CONTEXTS_MESSAGE)
    return playwright, browser


def dump_history(
    page: Page,
    history_url: str,
    scrolls: int,
    scroll_px: int,
    wait_ms: int,
) -> str:
    """Open the history page, scroll, and return the visible body text."""
    page.goto(history_url, wait_until="networkidle", timeout=120000)
    page.wait_for_timeout(3000)

    for _ in range(scrolls):
        page.mouse.wheel(0, scroll_px)
        page.wait_for_timeout(wait_ms)

    return page.locator("body").inner_text()


def main() -> int:
    """Connect to the browser, open history, and write a text dump."""
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)

    playwright, browser = connect_browser(args.cdp_url)
    try:
        context = browser.contexts[0]
        page = context.new_page()
        body_text = dump_history(
            page,
            args.history_url,
            args.scrolls,
            args.scroll_px,
            args.wait_ms,
        )
        args.output.write_text(body_text, encoding="utf-8")

        metadata = {
            "cdp_url": args.cdp_url,
            "history_url": args.history_url,
            "final_url": page.url,
            "title": page.title(),
            "output": str(args.output),
            "scrolls": args.scrolls,
            "scroll_px": args.scroll_px,
            "wait_ms": args.wait_ms,
        }
        if args.metadata_output:
            args.metadata_output.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        print(json.dumps(metadata, indent=2, ensure_ascii=False))
    finally:
        browser.close()
        playwright.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
