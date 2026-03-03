# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.57.0", "PyYAML"]
# ///
"""
fonecta_lookup.py — Reverse-lookup Finnish phone numbers via Fonecta Caller.

Logs in to fonecta.fi with the provided credentials, looks up each phone number
at https://www.fonecta.fi/haku/<local-number>, and extracts the name from the
__NEXT_DATA__ JSON embedded in the page (dehydratedState → queries → search results).

Credentials are read from the FONECTA_EMAIL and FONECTA_PASSWORD environment
variables. Never hard-code them.

Usage:
    FONECTA_EMAIL=user@example.com FONECTA_PASSWORD=secret \\
        uv run scripts/fonecta_lookup.py \\
            --phones 358401234567 358407654321 \\
            --output results.yaml

    # or read phones from a file (one per line, with or without leading +):
    FONECTA_EMAIL=... FONECTA_PASSWORD=... \\
        uv run scripts/fonecta_lookup.py \\
            --phones-file phones.txt \\
            --output results.yaml

Exit codes:
    0  all done (some lookups may still be empty — not found in Fonecta)
    1  login failed or unrecoverable error
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import yaml


# ── Phone helpers ─────────────────────────────────────────────────────────────

def normalise(ph: str) -> str:
    """Strip formatting and return bare E.164 digits (no leading +).

    Examples:
        '+358 40 123 4567' → '358401234567'
        '040 123 4567'     → '358401234567'  (Finnish local → E.164)
        '0041 …'           → '41…'
    """
    digits = re.sub(r"\D", "", ph)
    if digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0"):
        digits = "358" + digits[1:]
    return digits


def to_local(e164: str) -> str:
    """'358401234567' → '0401234567' (Finnish local format used by Fonecta URLs)."""
    if e164.startswith("358"):
        return "0" + e164[3:]
    return e164


# ── Browser helpers ───────────────────────────────────────────────────────────

async def login(page) -> None:
    """Log in to fonecta.fi using credentials from environment variables."""
    email    = os.environ["FONECTA_EMAIL"]
    password = os.environ["FONECTA_PASSWORD"]

    await page.goto("https://www.fonecta.fi/", wait_until="networkidle")

    # Accept cookie consent banner (always present on first load)
    try:
        await page.click("#onetrust-accept-btn-handler", timeout=5_000)
        await page.wait_for_timeout(500)
    except Exception:
        pass  # banner already dismissed or absent

    # Open login dialog
    await page.locator("button", has_text="Kirjaudu sisään").first.click()
    await page.wait_for_timeout(1_500)

    # Step 1: email
    await page.fill("input[name='email']", email)
    await page.locator("button", has_text="Seuraava").click()
    await page.wait_for_timeout(2_000)

    # Step 2: password — click inside the MUI Dialog to avoid the nav button
    await page.fill("input[name='password']", password)
    dialog = page.locator("div[role='presentation'].MuiDialog-root")
    await dialog.locator("button", has_text="Kirjaudu sisään").click()
    await page.wait_for_timeout(3_000)

    # Verify login succeeded by checking for the auth token appearance
    text = await page.inner_text("body")
    if "PRO" not in text and "Antti" not in text:
        # Generic check: look for the user's first name in the top bar
        # (Fonecta shows "FirstName" + "PRO" badge when logged in as Pro)
        raise RuntimeError("Login appears to have failed — check credentials")


def extract_name(page_props: dict) -> str | None:
    """Return best name from dehydratedState search results.

    Prefers a PERSON result over a COMPANY result: when a phone number is
    registered to both a company and a person (e.g. sole trader), the person
    name is more useful for identifying who sent a WhatsApp message.
    """
    for query in page_props.get("dehydratedState", {}).get("queries", []):
        key = query.get("queryKey", [])
        if isinstance(key, list) and key and key[0] == "search":
            results = query.get("state", {}).get("data", {}).get("results", [])
            person_name: str | None = None
            company_name: str | None = None
            for result in results:
                name = result.get("displayName") or result.get("name")
                if not name:
                    continue
                if result.get("contactType") == "PERSON":
                    if person_name is None:
                        person_name = name
                else:
                    if company_name is None:
                        company_name = name
            return person_name or company_name
    return None


async def lookup_number(page, phone_e164: str) -> str | None:
    """Look up one phone number; return display name or None."""
    local = to_local(phone_e164)
    await page.goto(
        f"https://www.fonecta.fi/haku/{local}",
        wait_until="networkidle",
        timeout=20_000,
    )
    await page.wait_for_timeout(300)

    content = await page.content()
    nd_match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        content,
        re.DOTALL,
    )
    if not nd_match:
        return None

    try:
        data = json.loads(nd_match.group(1))
        page_props = data.get("props", {}).get("pageProps", {})
        return extract_name(page_props)
    except (json.JSONDecodeError, KeyError):
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

async def run(phones: list[str], output: Path) -> None:
    from playwright.async_api import async_playwright

    # Load existing results so reruns are incremental
    results: dict[str, str | None] = {}
    if output.exists():
        results = yaml.safe_load(output.read_text()) or {}

    remaining = [p for p in phones if p not in results]
    print(f"{len(phones)} phones total, {len(results)} already cached, "
          f"{len(remaining)} to look up.")

    if not remaining:
        print("Nothing to do.")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="fi-FI",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        print("Logging in…")
        await login(page)
        print("Logged in.\n")

        found = 0
        for i, phone in enumerate(remaining, 1):
            name = await lookup_number(page, phone)
            results[phone] = name
            status = f"✓ {name}" if name else "–"
            print(f"  [{i:3d}/{len(remaining)}] +{phone} → {status}")
            if name:
                found += 1

            # Save incrementally every 10 lookups
            if i % 10 == 0:
                output.write_text(
                    yaml.dump(results, allow_unicode=True, default_flow_style=False)
                )

        output.write_text(
            yaml.dump(results, allow_unicode=True, default_flow_style=False)
        )
        await browser.close()

    print(f"\nDone: {found}/{len(remaining)} names found.")
    print(f"Results written to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--phones", nargs="+", metavar="PHONE",
        help="Phone number(s) in any format (+358…, 0…, 358…)",
    )
    group.add_argument(
        "--phones-file", metavar="FILE",
        help="File with one phone number per line",
    )
    parser.add_argument(
        "--output", default="fonecta-names.yaml", metavar="FILE",
        help="Output YAML file (default: fonecta-names.yaml)",
    )
    args = parser.parse_args()

    # Validate credentials
    if not os.environ.get("FONECTA_EMAIL") or not os.environ.get("FONECTA_PASSWORD"):
        print("Error: set FONECTA_EMAIL and FONECTA_PASSWORD environment variables.")
        sys.exit(1)

    # Collect and normalise phones
    if args.phones_file:
        raw = Path(args.phones_file).read_text().splitlines()
    else:
        raw = args.phones

    phones = [normalise(p) for p in raw if p.strip()]
    phones = [p for p in phones if p]  # drop blanks

    asyncio.run(run(phones, Path(args.output)))


if __name__ == "__main__":
    main()
