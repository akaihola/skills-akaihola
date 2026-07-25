#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx", "beautifulsoup4", "lxml"]
# ///
"""Search and extract articles from kuluttaja.fi via WordPress REST API.

Uses the built-in WP REST API instead of browser automation,
making it fast and dependency-light.

Usage:
    # Search articles
    ./extract.py --search "kaasugrilli"

    # Extract by post ID or slug
    ./extract.py --id 249062
    ./extract.py --slug puhdista-grillin-ritilat-lampimana-helpot-ohjeet-grillin-kunnossapitoon

    # Search with limit
    ./extract.py --search "grilli" --limit 5

    # JSON output
    ./extract.py --search "kaasugrilli" --json

    # List latest tests
    ./extract.py --latest-tests

    # List magazine issues
    ./extract.py --magazines
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from html import unescape
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

BASE = "https://kuluttaja.fi"
WP_API = f"{BASE}/wp-json"
CUSTOM_API = f"{WP_API}/kuluttaja/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
}

# ── API calls ─────────────────────────────────────────────────────────────────

def _client(auth: tuple | None = None) -> httpx.Client:
    c = httpx.Client(headers=HEADERS, timeout=30)
    if auth:
        c.auth = auth
    return c


def search_posts(query: str, *, limit: int = 10, offset: int = 0,
                 auth: tuple | None = None) -> list[dict]:
    """Search posts via WP REST API.
    
    Full post data including content.rendered (HTML), yoast_head_json,
    categories, tags, writer, and meta fields are returned.
    """
    params = {
        "search": query,
        "per_page": min(limit, 100),
        "offset": offset,
    }
    # Include embedded author and term data
    r = httpx.get(f"{WP_API}/wp/v2/posts", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def get_post(post_id: int, *, auth: tuple | None = None) -> dict:
    """Get a single post by ID."""
    params = {"_embed": "true"}
    r = httpx.get(f"{WP_API}/wp/v2/posts/{post_id}", params=params,
                  headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def get_post_by_slug(slug: str) -> dict:
    """Get post by slug."""
    params = {"slug": slug, "per_page": 1}
    r = httpx.get(f"{WP_API}/wp/v2/posts", params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise ValueError(f"No post found with slug: {slug}")
    return data[0]


def product_reviews_search(query: str, *, limit: int = 10) -> list[dict]:
    """Search product reviews via custom API.
    
    Endpoints discovered from site's WP REST index:
    - /kuluttaja/v1/product-reviews/search?search=<q>&per_page=<N>
    """
    params = {"search": query, "per_page": limit}
    r = httpx.get(f"{CUSTOM_API}/product-reviews/search", params=params,
                  headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def latest_test_winners(*, limit: int = 3) -> list[dict]:
    """Get latest test winners."""
    params = {"limit": limit}
    r = httpx.get(f"{CUSTOM_API}/product-reviews/latest-test-winners",
                  params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def latest_tests_posts() -> list[dict]:
    """Get latest test posts."""
    r = httpx.get(f"{CUSTOM_API}/test-category-navigation/latest-tests-posts",
                  headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def magazine_issues() -> list[dict]:
    """List magazine issues."""
    r = httpx.get(f"{CUSTOM_API}/magazine/latest", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("magazines", [])


# ── Content extraction ───────────────────────────────────────────────────────

def extract_metadata(post: dict) -> dict:
    """Extract clean metadata from a WP REST API post object."""
    yoast = post.get("yoast_head_json", {})
    meta = post.get("meta", {})
    author_info = ""
    
    # Author from embedded data or yoast
    if "_embedded" in post:
        authors = post["_embedded"].get("author", [])
        if authors:
            author_info = authors[0].get("name", "")
    if not author_info:
        twitter_misc = yoast.get("twitter_misc", {})
        author_info = twitter_misc.get("Kirjoittanut", "")
    
    # Date from yoast schema
    published = None
    schema = yoast.get("schema", {})
    if schema:
        graph = schema.get("@graph", [])
        for item in graph:
            if item.get("@type") == "Article":
                published = item.get("datePublished")
                break
    
    # Tags
    tags = []
    if "_embedded" in post:
        tag_list = post["_embedded"].get("wp:term", [])
        if tag_list and len(tag_list) > 1:
            tags = [t["name"] for t in tag_list[1]]  # second taxonomy is post_tag
    
    return {
        "id": post.get("id"),
        "title": post.get("title", {}).get("rendered", ""),
        "slug": post.get("slug", ""),
        "link": post.get("link", ""),
        "date": post.get("date", "").split("T")[0] if post.get("date") else "",
        "date_gmt": post.get("date_gmt", ""),
        "published": published.split("T")[0] if published else "",
        "author": author_info,
        "excerpt": post.get("excerpt", {}).get("rendered", ""),
        "tags": tags,
        "categories": post.get("categories", []),
        "featured_media": post.get("featured_media"),
        "is_paywalled": "access-restricted" in post.get("class_list", []),
    }


def extract_body(content_html: str) -> str:
    """Extract clean article body from content.rendered HTML.
    
    Strategy:
    - Remove paywall section (div#paywall-section)
    - Convert remaining HTML to text
    - Strip WooCommerce/social sharing buttons
    """
    soup = BeautifulSoup(content_html, "lxml")
    
    # Remove paywall sections
    for paywall in soup.select("#paywall-section, #paywall-product-selection"):
        paywall.decompose()
    
    # Remove WooCommerce share buttons, scripts, style tags
    for el in soup.select("script, style, [class*='share-buttons'], [class*='woocommerce'], iframe"):
        el.decompose()
    
    # Remove navigation elements and footers
    for el in soup.select("nav, footer, [class*='pagination'], [class*='related-posts']"):
        el.decompose()
    
    # Get the content as clean markdown-like text
    text = soup.get_text(separator="\n", strip=True)
    
    # Post-processing: clean up excessive newlines and empty lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    
    return text


def post_to_markdown(post: dict) -> str:
    """Convert a WP REST API post to a clean markdown document."""
    meta = extract_metadata(post)
    body = extract_body(post.get("content", {}).get("rendered", ""))
    
    parts = [
        f"# {meta['title']}",
        "",
        f"**Lähde:** Kuluttaja.fi",
        f"**Julkaistu:** {meta['published'] or meta['date'] or 'N/A'}",
        f"**Kirjoittaja:** {meta['author'] or 'N/A'}",
        f"**URL:** {meta['link']}",
    ]
    if meta.get("is_paywalled"):
        parts.append("**Huom:** Sisältö on osin lukumuurin takana. Kirjaudu sisään nähdäksesi koko artikkelin.")
    parts.append("")
    parts.append("---")
    parts.append("")
    parts.append(body)
    parts.append("")
    
    return "\n".join(parts)


# ── Search result formatting ────────────────────────────────────────────────

def format_search_result(post: dict, idx: int) -> str:
    """Format a search result for terminal display."""
    meta = extract_metadata(post)
    excerpt = BeautifulSoup(meta["excerpt"], "lxml").get_text(strip=True)[:150]
    paywall_tag = " 🔒" if meta["is_paywalled"] else ""
    
    lines = [f"  {idx}. {meta['title']}{paywall_tag}"]
    if meta.get("date"):
        lines.append(f"     Date: {meta['date']}")
    lines.append(f"     URL: {meta['link']}")
    if excerpt:
        lines.append(f"     {excerpt}...")
    if meta.get("tags"):
        lines.append(f"     Tags: {', '.join(meta['tags'][:5])}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Extract articles from kuluttaja.fi via WP REST API")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--search", metavar="QUERY", help="Search articles")
    group.add_argument("--id", type=int, metavar="ID", help="Article post ID")
    group.add_argument("--slug", metavar="SLUG", help="Article slug")
    group.add_argument("--latest-tests", action="store_true", help="List latest test posts")
    group.add_argument("--test-winners", action="store_true", help="List latest test winners")
    group.add_argument("--product-search", metavar="QUERY", help="Search product reviews")
    group.add_argument("--magazines", action="store_true", help="List magazine issues")
    
    parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON")
    parser.add_argument("--output-dir", default=None, help="Dir to save markdown files")
    
    args = parser.parse_args()
    
    # ── Search articles ────────────────────────────────────────────────
    if args.search:
        print(f"Searching for '{args.search}'…\n")
        posts = search_posts(args.search, limit=args.limit)
        
        if not posts:
            print("No results found.")
            return
        
        # Display results
        for i, p in enumerate(posts, 1):
            print(format_search_result(p, i))
            print()
        
        if args.output_json:
            results = []
            for p in posts:
                meta = extract_metadata(p)
                body = extract_body(p.get("content", {}).get("rendered", ""))
                results.append({**meta, "body": body})
            print(json.dumps({"query": args.search, "results": results}, ensure_ascii=False, indent=2))
            return
        
        # Extract and save as markdown
        out_dir = Path(args.output_dir or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        
        for post in posts:
            md = post_to_markdown(post)
            meta = extract_metadata(post)
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", meta["title"])[:60].strip(" .-_")
            path = out_dir / f"{safe_name}.md"
            path.write_text(md, encoding="utf-8")
            paywall = " 🔒 paywalled" if meta["is_paywalled"] else ""
            print(f"  Saved → {path.name}{paywall}")
        
        print(f"\nDone. {len(posts)} article(s) extracted to {out_dir}")

    # ── Single article by ID or slug ───────────────────────────────────
    elif args.id:
        post = get_post(args.id)
        if args.output_json:
            meta = extract_metadata(post)
            body = extract_body(post.get("content", {}).get("rendered", ""))
            print(json.dumps({**meta, "body": body}, ensure_ascii=False, indent=2))
        else:
            md = post_to_markdown(post)
            out_dir = Path(args.output_dir or ".")
            out_dir.mkdir(parents=True, exist_ok=True)
            title = post.get("title", {}).get("rendered", "article")
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", title)[:60].strip(" .-_")
            path = out_dir / f"{safe_name}.md"
            path.write_text(md, encoding="utf-8")
            print(f"Saved → {path}")

    elif args.slug:
        post = get_post_by_slug(args.slug)
        if args.output_json:
            meta = extract_metadata(post)
            body = extract_body(post.get("content", {}).get("rendered", ""))
            print(json.dumps({**meta, "body": body}, ensure_ascii=False, indent=2))
        else:
            md = post_to_markdown(post)
            out_dir = Path(args.output_dir or ".")
            out_dir.mkdir(parents=True, exist_ok=True)
            title = post.get("title", {}).get("rendered", "article")
            safe_name = re.sub(r'[<>:"/\\|?*]', "_", title)[:60].strip(" .-_")
            path = out_dir / f"{safe_name}.md"
            path.write_text(md, encoding="utf-8")
            print(f"Saved → {path}")

    # ── Specialty endpoints ────────────────────────────────────────────
    elif args.latest_tests:
        posts = latest_tests_posts()
        if args.output_json:
            print(json.dumps(posts, ensure_ascii=False, indent=2))
        else:
            for i, p in enumerate(posts, 1):
                title = p.get("title", {}).get("rendered", p.get("post_title", "?"))
                link = p.get("link", p.get("guid", {}).get("rendered", "?"))
                date = p.get("date", p.get("post_date", ""))[:10] if p.get("date") or p.get("post_date") else ""
                print(f"  {i}. {title}")
                if date:
                    print(f"     Date: {date}")
                print(f"     URL: {link}")
                print()

    elif args.test_winners:
        winners = latest_test_winners(limit=args.limit)
        if args.output_json:
            print(json.dumps(winners, ensure_ascii=False, indent=2))
        else:
            for i, w in enumerate(winners, 1):
                title = w.get("title", w.get("post_title", "?"))
                link = w.get("link", w.get("guid", {}).get("rendered", "?"))
                print(f"  {i}. {title}")
                print(f"     URL: {link}")
                print()

    elif args.product_search:
        results = product_reviews_search(args.product_search, limit=args.limit)
        if args.output_json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            for i, r in enumerate(results, 1):
                title = r.get("title", r.get("post_title", "?"))
                print(f"  {i}. {title}")
                if r.get("link") or r.get("guid", {}).get("rendered"):
                    print(f"     URL: {r.get('link') or r.get('guid', {}).get('rendered', '')}")
                print()

    elif args.magazines:
        issues = magazine_issues()
        if args.output_json:
            print(json.dumps(issues, ensure_ascii=False, indent=2))
        else:
            for i, m in enumerate(issues, 1):
                print(f"  {i}. {m['title']} ({m['publish_year']})")
                print(f"     URL: {m['permalink']}")
                print()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
