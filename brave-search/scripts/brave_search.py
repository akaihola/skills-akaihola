#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "httpx>=0.27.0",
# ]
# ///

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Iterable, List, Tuple

import httpx

API_BASE_URL = "https://api.search.brave.com"
ENDPOINT_PATHS = {
    "web": "/res/v1/web/search",
    "summarizer": "/res/v1/summarizer/search",
}


class BraveSearchError(Exception):
    """Raised when the Brave API reports an error."""

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.details = details


def _load_api_key() -> str:
    key = os.getenv("BRAVE_SEARCH_API_KEY")
    if not key:
        raise BraveSearchError(
            "Environment variable BRAVE_SEARCH_API_KEY is required.",
            details={"missing_env": "BRAVE_SEARCH_API_KEY"},
        )
    return key


def _bool_to_string(value: bool) -> str:
    return "true" if value else "false"


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def _build_web_query_params(params: Dict[str, Any]) -> List[Tuple[str, str]]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object with query parameters.")
    query = params.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("`query` (string) is required for web search.")
    items: List[Tuple[str, str]] = [("q", query.strip())]

    summary_flag = bool(params.get("summary"))
    result_filter = params.get("result_filter")

    if summary_flag:
        items.append(("result_filter", "summarizer"))
    elif result_filter:
        filters = _normalize_list(result_filter)
        if filters:
            items.append(("result_filter", ",".join(filters)))

    goggles = _normalize_list(params.get("goggles"))
    for goggle in goggles:
        if goggle.startswith("https://"):
            items.append(("goggles", goggle))

    direct_fields = [
        "country",
        "search_lang",
        "ui_lang",
        "safesearch",
        "freshness",
        "units",
        "count",
        "offset",
    ]
    bool_fields = ["text_decorations", "spellcheck", "extra_snippets"]

    for field in direct_fields:
        value = params.get(field)
        if value is None:
            continue
        items.append((field, str(value)))

    for field in bool_fields:
        value = params.get(field)
        if value is None:
            continue
        items.append((field, _bool_to_string(bool(value))))

    return items


def _build_summarizer_query_params(
    params: Dict[str, Any],
) -> Tuple[List[Tuple[str, str]], bool]:
    if not isinstance(params, dict):
        raise ValueError("params must be an object with summarizer inputs.")
    key = params.get("key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("`key` (string) is required for summarizer.")
    inline_refs = bool(params.get("inline_references", False))
    query_items = [
        ("key", key.strip()),
        ("entity_info", _bool_to_string(bool(params.get("entity_info", False)))),
        ("inline_references", _bool_to_string(inline_refs)),
    ]
    return query_items, inline_refs


def issue_request(
    endpoint: str, query_items: Iterable[Tuple[str, str]]
) -> Dict[str, Any]:
    if endpoint not in ENDPOINT_PATHS:
        raise BraveSearchError(f"Unsupported endpoint '{endpoint}'.")
    api_key = _load_api_key()
    url = f"{API_BASE_URL}{ENDPOINT_PATHS[endpoint]}"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    try:
        response = httpx.get(
            url, headers=headers, params=list(query_items), timeout=30.0
        )
    except httpx.HTTPError as exc:
        raise BraveSearchError(
            "Failed to reach Brave API.", details={"error": str(exc)}
        ) from exc

    if response.status_code // 100 != 2:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        raise BraveSearchError(
            f"Brave API responded with status {response.status_code}.",
            details=payload,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise BraveSearchError("Brave API returned invalid JSON.") from exc


def _format_web_results(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    for item in section.get("results", []) or []:
        results.append(
            {
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "extra_snippets": item.get("extra_snippets"),
            }
        )
    return results


def _format_faq_results(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = []
    for item in section.get("results", []) or []:
        results.append(
            {
                "question": item.get("question"),
                "answer": item.get("answer"),
                "title": item.get("title"),
                "url": item.get("url"),
            }
        )
    return results


def _format_discussion_results(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    mutated = section.get("mutated_by_goggles")
    results = []
    for item in section.get("results", []) or []:
        results.append(
            {
                "mutated_by_goggles": mutated,
                "url": item.get("url"),
                "data": item.get("data"),
            }
        )
    return results


def _format_news_results(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    mutated = section.get("mutated_by_goggles")
    results = []
    for item in section.get("results", []) or []:
        results.append(
            {
                "mutated_by_goggles": mutated,
                "source": item.get("source"),
                "breaking": item.get("breaking"),
                "is_live": item.get("is_live"),
                "age": item.get("age"),
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "extra_snippets": item.get("extra_snippets"),
            }
        )
    return results


def _format_video_results(section: Dict[str, Any]) -> List[Dict[str, Any]]:
    mutated = section.get("mutated_by_goggles")
    results = []
    for item in section.get("results", []) or []:
        video_data = item.get("video", {}) or {}
        results.append(
            {
                "mutated_by_goggles": mutated,
                "url": item.get("url"),
                "title": item.get("title"),
                "description": item.get("description"),
                "age": item.get("age"),
                "thumbnail_url": (item.get("thumbnail") or {}).get("src"),
                "duration": video_data.get("duration"),
                "view_count": video_data.get("views"),
                "creator": video_data.get("creator"),
                "publisher": video_data.get("publisher"),
                "tags": video_data.get("tags"),
            }
        )
    return results


def run_web_search(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        query_items = _build_web_query_params(params)
        response = issue_request("web", query_items)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except BraveSearchError as exc:
        payload: Dict[str, Any] = {"ok": False, "error": str(exc)}
        if exc.details is not None:
            payload["details"] = exc.details
        return payload

    web_section = response.get("web") or {}
    web_results = _format_web_results(web_section)

    if not web_results:
        return {"ok": False, "error": "No web results found"}

    result_payload = {
        "ok": True,
        "web_results": web_results,
        "faq_results": _format_faq_results(response.get("faq") or {}),
        "discussions_results": _format_discussion_results(
            response.get("discussions") or {}
        ),
        "news_results": _format_news_results(response.get("news") or {}),
        "video_results": _format_video_results(response.get("videos") or {}),
        "summarizer_key": (response.get("summarizer") or {}).get("key"),
        "raw_query_info": response.get("query"),
    }
    return result_payload


def _flatten_summary(summary_items: List[Dict[str, Any]], inline_refs: bool) -> str:
    parts: List[str] = []
    for entry in summary_items:
        entry_type = entry.get("type")
        data = entry.get("data")
        if entry_type == "token" and isinstance(data, str):
            parts.append(data)
        elif entry_type == "inline_reference" and inline_refs:
            url = (data or {}).get("url")
            if url:
                parts.append(f" ({url})")
    return "".join(parts).strip()


def run_summarizer(params: Dict[str, Any]) -> Dict[str, Any]:
    try:
        query_items, inline_refs = _build_summarizer_query_params(params)
        poll_interval_ms = int(params.get("poll_interval_ms", 50))
        max_attempts = int(params.get("max_attempts", 20))
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    attempts = 0
    response: Dict[str, Any] | None = None
    while attempts < max_attempts:
        attempts += 1
        try:
            response = issue_request("summarizer", query_items)
        except BraveSearchError as exc:
            payload: Dict[str, Any] = {"ok": False, "error": str(exc)}
            if exc.details is not None:
                payload["details"] = exc.details
            return payload

        if response.get("status") == "complete":
            break
        time.sleep(max(poll_interval_ms, 0) / 1000.0)
    else:
        return {"ok": False, "error": "Unable to retrieve a Summarizer summary."}

    summary_items = response.get("summary") or []
    if not summary_items:
        return {"ok": False, "error": "Unable to retrieve a Summarizer summary."}

    return {
        "ok": True,
        "summary_text": _flatten_summary(summary_items, inline_refs),
        "summary_raw": summary_items,
        "enrichments": response.get("enrichments"),
        "followups": response.get("followups"),
        "entities_infos": response.get("entities_infos"),
    }


def _parse_params_json(raw: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON for --params-json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--params-json must decode to a JSON object.")
    return parsed


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Brave Search skill helper.")
    parser.add_argument(
        "mode", choices=["web", "summarizer"], help="Which operation to perform."
    )
    parser.add_argument(
        "--params-json",
        required=True,
        metavar="JSON",
        help="JSON object containing parameters for the requested operation.",
    )
    return parser


def main(argv: List[str]) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        params = _parse_params_json(args.params_json)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    if args.mode == "web":
        result = run_web_search(params)
    else:
        result = run_summarizer(params)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
