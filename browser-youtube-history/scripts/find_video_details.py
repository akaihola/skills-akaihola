#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.13"
# dependencies = ["playwright==1.57.0"]
# ///

"""Open a YouTube video in a logged-in browser session and extract visible details."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Error, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

DEFAULT_OUTPUT = (
    Path.home() / ".cache" / "browser-youtube-history" / "video-details.txt"
)
NO_CONTEXTS_MESSAGE = "No browser contexts found on the CDP endpoint."
DESCRIPTION_SELECTORS = [
    "tp-yt-paper-button#expand",
    'button[aria-label*="more" i]',
    'button[aria-label*="More" i]',
    "#description-inline-expander tp-yt-paper-button",
]


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=(
            "Open a YouTube video in a logged-in browser CDP session and dump text."
        )
    )
    parser.add_argument("url", help="YouTube watch URL to inspect")
    parser.add_argument(
        "--cdp-url",
        default="http://127.0.0.1:9222",
        help="Chrome DevTools Protocol HTTP endpoint (default: http://127.0.0.1:9222)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Path for the visible video page text dump",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=None,
        help="Optional path for JSON metadata extracted from the page",
    )
    parser.add_argument(
        "--expand-description",
        action="store_true",
        help="Try to click the description expander before dumping text",
    )
    return parser.parse_args()


def maybe_expand_description(page: Page) -> None:
    """Try to expand the YouTube description area if a known control is visible."""
    for selector in DESCRIPTION_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=1000):
                locator.click(timeout=1000)
                page.wait_for_timeout(1500)
                break
        except (Error, PlaywrightTimeoutError):
            continue


def main() -> int:
    """Connect to the browser, open the video, and dump visible page details."""
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.metadata_output:
        args.metadata_output.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            raise RuntimeError(NO_CONTEXTS_MESSAGE)

        context = browser.contexts[0]
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=120000)
        page.wait_for_timeout(5000)

        if args.expand_description:
            maybe_expand_description(page)

        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(1000)
        body_text = page.locator("body").inner_text()
        args.output.write_text(body_text, encoding="utf-8")

        metadata = {
            "url": args.url,
            "final_url": page.url,
            "title": page.title(),
            "output": str(args.output),
            "description_expanded": args.expand_description,
        }
        if args.metadata_output:
            args.metadata_output.write_text(
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

        print(json.dumps(metadata, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
