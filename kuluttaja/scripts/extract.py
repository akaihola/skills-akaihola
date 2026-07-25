#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright==1.57.0", "markdownify"]
# ///
"""Extract articles from kuluttaja.fi with optional login for paywalled content.

Usage:
    # Single URL (public)
    ./extract.py https://kuluttaja.fi/fi/artikkeli/bauhausin-grilli-polttaa-napit

    # Single URL (with login)
    KULUTTAJA_EMAIL=user@example.com KULUTTAJA_PASSWORD=secret \\
        ./extract.py https://kuluttaja.fi/fi/artikkeli/herkullista-grilliruokaa

    # Multiple URLs from a newline-delimited file
    KULUTTAJA_EMAIL=... KULUTTAJA_PASSWORD=secret \\
        ./extract.py --file urls.txt

    # Search for a term and extract top results
    KULUTTAJA_EMAIL=... KULUTTAJA_PASSWORD=secret \\
        ./extract.py --search "kaasugrilli" --limit 3

    # Specify output directory
    ./extract.py --search "kaasugrilli" --output-dir ./articles

    # Output as JSON instead of markdown files
    ./extract.py --search "grilli" --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import re
from pathlib import Path
from urllib.parse import urljoin

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Error: playwright is required. Install with:")
    print("  uv pip install playwright")
    print("  uv run playwright install chromium")
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_URL = "https://kuluttaja.fi"
LOGIN_URL = "https://kuluttaja.fi/fi/login"  # reached via Kirjaudu link
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def _nix_browser_executable() -> str | None:
    """Find the Playwright Chromium binary installed via Nix."""
    import glob
    candidates = glob.glob(
        "/nix/store/*-playwright-chromium/chrome-linux64/chrome"
    )
    return candidates[0] if candidates else None


def _find_nix_headless_shell() -> str | None:
    """Find the Playwright Chromium headless shell installed via Nix."""
    import glob
    candidates = glob.glob(
        "/nix/store/*-playwright-chromium-headless-shell"
        "/chrome-headless-shell-linux64/chrome-headless-shell"
    )
    return candidates[0] if candidates else None

# ── Browser helpers ───────────────────────────────────────────────────────────


def dismiss_cookies(page) -> None:
    """Dismiss the cookie consent banner if present."""
    for text in ["Hyväksy kaikki", "Vain välttämättömät"]:
        try:
            el = page.get_by_text(text).first
            if el.count():
                el.click(timeout=3_000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def login(page, email: str, password: str) -> None:
    """Log in to kuluttaja.fi.

    Flow observed via agent-browser:
    1. Go to homepage → click "KIRJAUDU" in the header
    2. Form has email and password textboxes plus a "PIDÄ MINUT KIRJAUTUNEENA" checkbox
    3. Click "Kirjaudu sisään" button
    4. After successful login, "KIRJAUDU ULOS" and "Oma tili" appear in header.
    """
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    dismiss_cookies(page)

    # Click the Kirjaudu link in the header
    page.get_by_text("KIRJAUDU").first.click(timeout=5_000)
    page.wait_for_timeout(1_000)

    # The login form has labelled textboxes for email and password
    # Sähköpostiosoite textbox
    email_box = page.get_by_role("textbox", name="SÄHKÖPOSTIOSOITE")
    password_box = page.get_by_role("textbox", name="SALASANA")

    email_box.fill(email, timeout=5_000)
    password_box.fill(password, timeout=5_000)

    # Optionally check "PIDÄ MINUT KIRJAUTUNEENA"
    try:
        page.get_by_text("PIDÄ MINUT KIRJAUTUNEENA").first.click(timeout=2_000)
    except Exception:
        pass

    # Click submit
    page.get_by_role("button", name="Kirjaudu sisään").first.click(timeout=5_000)
    page.wait_for_timeout(3_000)

    # Verify login succeeded
    body_text = page.inner_text("body")
    if "Kirjaudu ulos" not in body_text and "Oma tili" not in body_text:
        raise RuntimeError("Login failed — check KULUTTAJA_EMAIL / KULUTTAJA_PASSWORD")


def search(page, query: str, *, limit: int = 10) -> list[dict]:
    """Search kuluttaja.fi and return article results.

    Returns a list of dicts with keys: title, url, date, snippet.
    The search uses the site's built-in search box: ``input[name="s"]``
    (placeholder "Mitä etsit?", aria-label "Haku").
    """
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20_000)
    dismiss_cookies(page)

    # Fill the search box and submit
    # The search input has placeholder="Mitä etsit?" name="s" aria-label="Haku"
    searchbox = page.locator("input[name='s'][type='search']").first
    searchbox.fill(query, timeout=5_000)
    searchbox.press("Enter", timeout=5_000)
    page.wait_for_timeout(3_000)

    # Parse results — each result is in an <article> with a heading and link
    results = []
    articles = page.locator("article").all()
    for art in articles:
        try:
            heading = art.locator("h4, h3, h2, [class*='heading']").first
            title = heading.inner_text(timeout=2_000).strip()
        except Exception:
            title = ""

        try:
            link = art.locator("a").first
            href = link.get_attribute("href", timeout=2_000)
        except Exception:
            href = ""

        try:
            date_el = art.locator("text=/\\d{1,2}\\.\\d{2}\\.\\d{4}/").first
            date_str = date_el.inner_text(timeout=2_000).strip()
        except Exception:
            # Generic text that looks like a date
            date_str = ""

        try:
            snippet_el = art.locator("p, div[class*='excerpt']").first
            snippet = snippet_el.inner_text(timeout=2_000).strip()[:200]
        except Exception:
            snippet = ""

        if href:
            full_url = href if href.startswith("http") else urljoin(BASE_URL, href)
        else:
            full_url = ""

        if title:
            results.append({
                "title": title,
                "url": full_url,
                "date": date_str,
                "snippet": snippet,
            })

        if len(results) >= limit:
            break

    return results


def extract_article(page, url: str, *, logged_in: bool = False) -> dict:
    """Navigate to an article URL and extract its content as markdown.

    Structure observed: the article body is in <main> with:
    - h1 title
    - "JULKAISTU: DD.MM.YYYY" label
    - "KIRJOITTAJA: Name" label
    - Content paragraphs with "Näytä lisää" expand buttons
    - Tags at the bottom
    """
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    dismiss_cookies(page)
    page.wait_for_timeout(2_000)

    # Expand "Näytä lisää" / "NÄYTÄ LISÄÄ" buttons to reveal hidden content
    for btn_text in ["Näytä lisää", "NÄYTÄ LISÄÄ"]:
        try:
            while True:
                btn = page.get_by_text(btn_text).first
                if btn.count():
                    btn.click(timeout=3_000)
                    page.wait_for_timeout(800)
                else:
                    break
        except Exception:
            break

    # If behind paywall and not logged in, detect it
    paywalled = False
    body_text = page.inner_text("body")
    if "Jatka lukemista" in body_text or "Osta pääsy" in body_text:
        paywalled = True

    # Extract article metadata and content
    title = ""
    author = ""
    published = ""
    content_lines = []

    # Title from h1
    try:
        h1 = page.locator("h1").first
        title = h1.inner_text(timeout=2_000).strip()
    except Exception:
        pass

    # Published date — look for "JULKAISTU:" in the page text
    # It appears as a span/text like "JULKAISTU: 19.06.2025"
    for text_pattern in ["JULKAISTU:", "Julkaistu:"]:
        try:
            date_el = page.get_by_text(text_pattern).first
            if date_el.count():
                raw = date_el.inner_text(timeout=2_000).strip()
                published = raw.replace(text_pattern, "").strip()
                break
        except Exception:
            pass

    # Author — look for "KIRJOITTAJA:" label
    for text_pattern in ["KIRJOITTAJA:", "Kirjoittaja:"]:
        try:
            author_el = page.get_by_text(text_pattern).first
            if author_el.count():
                # Get the full text, take the part after the label
                raw = author_el.inner_text(timeout=2_000).strip()
                author = raw.replace(text_pattern, "").strip()
                break
        except Exception:
            pass

    # If the author is still not clean, try to extract more precisely
    # The author line is often "KIRJOITTAJA: ALEKSI VÄHIMAA"
    # But behind paywall it might just show as "KIRJOITTAJA: ALEKSI VÄHIMAA"
    # in the body. Let's parse it properly.
    if author and ":" in author:
        author = author.split(":", 1)[-1].strip()

    # Extract main content from the article body
    # Skip paywall section, sidebar, footer
    main_el = page.locator("main").first
    article_body_done = False
    if main_el.count():
        # Get all text content elements
        elements = main_el.locator("p, h2, h3, h4, h5, li").all()
        for el in elements:
            tag = el.evaluate("el => el.tagName.toLowerCase()")
            text = el.inner_text().strip()
            if not text:
                continue

            # Paywall section — stop extracting
            if "Jatka lukemista" in text or "Osta pääsy" in text:
                article_body_done = True
                continue
            if article_body_done:
                # After paywall we get metadata labels and tags — skip them
                if tag == "h2" and "Saatat pitää" in text:
                    break
                continue

            # Skip repetitive footer/sidebar
            if "Saatat pitää" in text:
                break
            if text.startswith("Lue artikkeli:"):
                continue

            # Skip metadata labels (author, images, publish date, tags)
            if (text.startswith("KIRJOITTAJA:") or text.startswith("KIRJOITTAJA ") or
                    text.startswith("KUVAT:") or text.startswith("KUVAT ") or
                    text.startswith("JULKAISTU:")):
                continue
            if text.startswith("Linkki kopioitu"):
                continue

            # Tags appear as short ALL-CAPS single words near the bottom of main.
            # Skip paragraphs that are short uppercase-only words (tags).
            if tag == "p" and len(text) < 30 and text.isupper() and " " not in text:
                # Likely a tag like "GRILLAUS", "GRILLI", etc.
                continue

            if tag in ("h2", "h3", "h4"):
                content_lines.append(f"\n## {text}")
            elif tag == "p":
                content_lines.append(f"\n{text}")
            elif tag == "li":
                content_lines.append(f"  - {text}")

    body = "\n".join(content_lines).strip()

    # Remove "Linkki kopioitu" and similar UI noise
    body = body.replace("Linkki kopioitu\n\n", "")

    return {
        "url": url,
        "title": title,
        "author": author,
        "published": published,
        "paywalled": paywalled,
        "body": body,
    }


def article_to_markdown(article: dict) -> str:
    """Convert an extracted article dict to a markdown string."""
    parts = [
        f"# {article['title']}",
        "",
        f"**Lähde:** Kuluttaja.fi",
        f"**Julkaistu:** {article['published'] or 'N/A'}",
        f"**Kirjoittaja:** {article['author'] or 'N/A'}",
        f"**URL:** {article['url']}",
    ]
    if article.get("paywalled"):
        parts.append("**Huom:** Sisältö on osin lukumuurin takana. Kirjaudu sisään nähdäksesi koko artikkelin.")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(article.get("body", "*Ei sisältöä saatavilla.*"))
    parts.append("")
    return "\n".join(parts)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract articles from kuluttaja.fi")
    parser.add_argument("url", nargs="?", help="Article URL(s) to extract")
    parser.add_argument("--file", help="File with one URL per line or search term")
    parser.add_argument("--search", help="Search term to find articles")
    parser.add_argument("--limit", type=int, default=10, help="Max search results or extracted articles (default: 10)")
    parser.add_argument("--output-dir", default=None, help="Directory to save markdown files (default: current dir)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON instead of markdown files")
    parser.add_argument("--login", action="store_true", help="Force login (reads KULUTTAJA_EMAIL/PASSWORD)")
    args = parser.parse_args()

    email = os.environ.get("KULUTTAJA_EMAIL", "")
    password = os.environ.get("KULUTTAJA_PASSWORD", "")

    if args.login and (not email or not password):
        print("Error: --login requires KULUTTAJA_EMAIL and KULUTTAJA_PASSWORD environment variables.")
        sys.exit(1)

    urls: list[str] = []
    search_results: list[dict] = []
    search_term: str | None = None

    if args.file:
        raw = Path(args.file).read_text().splitlines()
        urls = [line.strip() for line in raw if line.strip() and not line.startswith("#")]
    elif args.search:
        search_term = args.search
    elif args.url:
        urls = [args.url]
    else:
        parser.print_help()
        sys.exit(1)

    # Resolve browser executable on NixOS
    nix_exe = _nix_browser_executable() or _find_nix_headless_shell()
    launch_kwargs: dict = {"headless": True}
    if nix_exe:
        launch_kwargs["executable_path"] = nix_exe

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**launch_kwargs)
        ctx = browser.new_context(
            user_agent=USER_AGENT,
            locale="fi-FI",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        logged_in = False
        if args.login or (args.search and email and password):
            print("Logging in to kuluttaja.fi…")
            try:
                login(page, email, password)
                logged_in = True
                print("Logged in.")
            except Exception as e:
                print(f"Login failed: {e}")
                if args.login:
                    browser.close()
                    sys.exit(1)

        # Search mode
        if search_term is not None:
            print(f"Searching for '{search_term}'…")
            search_results = search(page, search_term, limit=args.limit)
            if not search_results:
                print("No results found.")
                if args.output_json:
                    print(json.dumps({"query": search_term, "results": []}, ensure_ascii=False, indent=2))
                browser.close()
                return

            if args.output_json:
                print(json.dumps({"query": search_term, "results": search_results}, ensure_ascii=False, indent=2))
                browser.close()
                return

            # Show search results
            print(f"\nFound {len(search_results)} results for '{search_term}':\n")
            for i, r in enumerate(search_results, 1):
                print(f"  {i}. {r['title']}")
                if r.get("date"):
                    print(f"     Date: {r['date']}")
                if r.get("url"):
                    print(f"     URL: {r['url']}")
                if r.get("snippet"):
                    print(f"     {r['snippet'][:120]}...")
                print()

            # Extract all found articles
            urls = [r["url"] for r in search_results if r["url"]]

        # Extract articles
        articles = []
        for i, url in enumerate(urls[:args.limit], 1):
            print(f"  Extracting [{i}/{min(len(urls), args.limit)}]: {url}")
            article = extract_article(page, url, logged_in=logged_in)
            if article.get("paywalled") and not logged_in:
                print(f"    (paywalled — re-run with --login or set KULUTTAJA_EMAIL/PASSWORD)")
            else:
                print(f"    ✓ {article['title']}")
            articles.append(article)

        browser.close()

    # Output
    if args.output_json:
        print(json.dumps({"articles": articles}, ensure_ascii=False, indent=2))
        return

    out_dir = Path(args.output_dir or ".")
    out_dir.mkdir(parents=True, exist_ok=True)

    for art in articles:
        if not art.get("title"):
            continue
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", art["title"])[:60].strip(" ._-")
        path = out_dir / f"{safe_name}.md"
        path.write_text(article_to_markdown(art), encoding="utf-8")
        print(f"  Saved → {path}")

    print(f"\nDone. {len(articles)} article(s) extracted to {out_dir}")


if __name__ == "__main__":
    main()
