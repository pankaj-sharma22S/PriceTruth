from __future__ import annotations

import gzip
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from .adapters import ADAPTERS, PlatformAdapter, adapter_for_url
from .adapters.registry import normalize_key
from .config import settings
from .matching import match_product
from .security import AccessCheckError, fetch_bounded_response, permitted_sitemaps, validate_permitted_page

log = logging.getLogger("pricetruth.discovery")
STOP_WORDS = {"with", "from", "this", "that", "new", "the", "and", "for", "inch", "india", "online", "buy", "shop", "at"}
COLORS = {"black", "white", "blue", "silver", "gold", "pink", "green", "purple", "red", "orange", "teal", "lavender", "sage", "midnight", "starlight", "ultramarine", "graphite", "titanium", "natural", "desert", "violet", "yellow", "grey", "gray", "brown", "cream"}
SEARCH_ROUTES = {
    "amazon_india": ("/s", "k"),
    "flipkart": ("/search", "q"),
    "shopsy": ("/search", "q"),
    "myntra": ("/search", "q"),
    "meesho": ("/search", "q"),
    "ajio": ("/search/", "text"),
    "croma": ("/searchB", "q"),
}


def _log(event: str, details: dict) -> None:
    log.info("%s %s", event, json.dumps(details, ensure_ascii=False, sort_keys=True, default=str))


def _request_timeout(deadline: float | None, configured: float) -> float:
    if deadline is None:
        return configured
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AccessCheckError("Overall discovery deadline reached; remaining requests were stopped.", "deadline_exceeded")
    return min(configured, remaining)


def _path_only(url: str) -> str:
    parts = urlparse(url)
    return urlunparse((parts.scheme, parts.netloc, parts.path, "", "", ""))


def _search_attributes(product: dict) -> dict:
    title = str(product.get("title") or "")
    specs = product.get("specs") or {}
    identifiers = product.get("identifiers") or {}
    brand = str(product.get("brand") or "").strip()
    brand_words = {word.lower() for word in re.findall(r"[a-z0-9]+", brand, re.I)}

    storage = []
    for key, value in specs.items():
        if any(word in str(key).lower() for word in ("storage", "capacity", "memory", "ssd", "rom")):
            storage.extend(re.findall(r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb)\b", str(value), re.I))
    storage.extend(re.findall(r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb)\b", title, re.I))
    storage = list(dict.fromkeys(re.sub(r"\s+", "", value).upper() for value in storage))

    color_parts = []
    for key, value in specs.items():
        if "color" in str(key).lower() or "colour" in str(key).lower():
            color_parts.extend(re.findall(r"[a-z]+", str(value), re.I))
    color_parts.extend(re.findall(r"[a-z]+", title, re.I))
    colors = list(dict.fromkeys(part.title() for part in color_parts if part.lower() in COLORS))

    brand_words = {word.lower() for word in re.findall(r"[a-z0-9]+", brand, re.I)}
    variant_words = set(COLORS)
    title_without_storage = re.sub(r"\b\d+(?:\.\d+)?\s*(?:gb|tb|mb)\b", " ", title, flags=re.I)
    family_words = [word for word in re.findall(r"[a-z0-9]+", title_without_storage, re.I)
                    if word.lower() not in brand_words and word.lower() not in variant_words
                    and word.lower() not in STOP_WORDS]
    family = " ".join(family_words)
    model = str(product.get("model") or "").strip()
    sku = str(identifiers.get("sku") or "").strip()
    mpn = str(identifiers.get("mpn") or "").strip()
    gtin = str(identifiers.get("gtin") or "").strip()

    other = []
    relevant = ("ram", "memory", "processor", "cpu", "gpu", "screen", "display", "size", "series")
    for key, value in specs.items():
        if any(word in str(key).lower() for word in relevant):
            value = str(value).strip()
            if value and normalize_key(value) not in {normalize_key(x) for x in [brand, family, model, *storage, *colors]}:
                other.append(value)
    return {"brand": brand, "family": family, "model": model, "storage": storage,
            "color": colors, "other_variant": list(dict.fromkeys(other)),
            "mpn": mpn, "gtin": gtin, "sku": sku}


def build_search_queries(product: dict, platform_key: str) -> list[dict]:
    attrs = _search_attributes(product)
    base = [attrs["brand"], attrs["family"], attrs["model"]]
    global_ids = [attrs["mpn"], attrs["gtin"]]
    if platform_key == product.get("origin_platform") and attrs["sku"]:
        global_ids.append(attrs["sku"])
    variant = [*attrs["storage"], *attrs["color"], *attrs["other_variant"]]
    primary = " ".join(part for part in [*base, *variant, *global_ids] if part)
    fallback_storage = [re.sub(r"(\d+(?:\.\d+)?)(GB|TB|MB)", r"\1 \2", value, flags=re.I) for value in attrs["storage"]]
    fallback = " ".join(part for part in [attrs["brand"], attrs["family"], attrs["model"], *attrs["color"], *fallback_storage, *attrs["other_variant"], *global_ids] if part)
    queries = []
    for name, query in (("primary", primary), ("fallback", fallback)):
        query = re.sub(r"\s+", " ", query).strip()[:180]
        if query and query not in [item["query"] for item in queries]:
            queries.append({"kind": name, "query": query})
    return queries


def build_search_query(product: dict, platform_key: str | None = None) -> str:
    key = platform_key or str(product.get("origin_platform") or "")
    queries = build_search_queries(product, key)
    return queries[0]["query"] if queries else ""


def is_product_page_url(platform_key: str, url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    patterns = {
        "amazon_india": r"/(?:dp|gp/product|gp/aw/d)/[A-Z0-9]{10}(?:/|$)",
        "flipkart": r"/(?:p|dl)/[a-z0-9]+(?:/|$)",
        "shopsy": r"/(?:p|dl)/[a-z0-9]+(?:/|$)",
        "myntra": r"/(?:.+/)?(?:\d+/buy|p/\d+)$",
        "meesho": r"/.+/p/[^/]+$",
        "ajio": r"/.+/p/[^/]+$",
        "croma": r"/.+/p/[^/]+$",
    }
    return bool(re.search(patterns.get(platform_key, r"(?!)"), path, re.I))


def extract_candidate_urls(html: str, search_url: str, platform_key: str, link_limit: int = 2000) -> dict:
    adapter = ADAPTERS[platform_key]
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.select("a[href]")
    candidates, seen = [], set()
    candidate_titles: dict[str, str] = {}
    pagination_links = 0
    for anchor in anchors:
        href = anchor.get("href") or ""
        rel = anchor.get("rel") or []
        query = parse_qs(urlparse(href).query)
        if "next" in [str(item).lower() for item in rel] or any(key.lower() in {"page", "p", "pageindex", "start", "offset"} for key in query):
            pagination_links += 1
    counts = {"links_seen": min(len(anchors), link_limit), "rejected_other_domain": 0,
              "rejected_non_product": 0, "duplicates": 0, "redirect_wrappers_unwrapped": 0,
              "pagination_links_seen": pagination_links, "truncated": len(anchors) > link_limit}
    for anchor in anchors[:link_limit]:
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            counts["rejected_non_product"] += 1
            continue
        url = urljoin(search_url, href)
        parts = urlparse(url)
        wrapped = parse_qs(parts.query).get("url", [])
        if wrapped:
            nested = urljoin(url, wrapped[0])
            if adapter.supports_url(nested) and is_product_page_url(platform_key, nested):
                url = nested
                parts = urlparse(url)
                counts["redirect_wrappers_unwrapped"] += 1
        if parts.scheme != "https" or not adapter.supports_url(url):
            counts["rejected_other_domain"] += 1
            continue
        url = urlunparse((parts.scheme, parts.netloc, parts.path, parts.params, parts.query, ""))
        if platform_key == "amazon_india":
            asin = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?:/|$)", parts.path, re.I)
            if asin:
                url = f"https://{parts.netloc}/dp/{asin.group(1).upper()}"
                parts = urlparse(url)
        if not is_product_page_url(platform_key, url):
            counts["rejected_non_product"] += 1
            continue
        if url in seen:
            counts["duplicates"] += 1
            continue
        seen.add(url)
        candidates.append(url)
        label = " ".join((anchor.get_text(" ", strip=True), anchor.get("aria-label", ""),
                          anchor.get("title", ""), " ".join(img.get("alt", "") for img in anchor.select("img[alt]"))))
        label = re.sub(r"\s+", " ", label).strip()
        if label:
            candidate_titles[url] = label[:300]
    counts["product_urls_extracted"] = len(candidates)
    return {"urls": candidates, "titles": candidate_titles, "counts": counts}


def _search_url(adapter: PlatformAdapter, query: str) -> str:
    path, parameter = SEARCH_ROUTES[adapter.platform.key]
    return f"https://www.{adapter.platform.domains[0]}{path}?{urlencode({parameter: query})}"


def _search_attempt(adapter: PlatformAdapter, query: dict, deadline: float | None = None) -> dict:
    url = _search_url(adapter, query["query"])
    started = time.perf_counter()
    details = {"kind": query["kind"], "query": query["query"], "request_url": url,
               "request_attempted": False, "http_status": None, "content_type": None,
               "response_bytes": 0, "candidate_urls_extracted": 0, "parser_status": "not_run"}
    try:
        validate_permitted_page(url, deadline=deadline)
    except ValueError as exc:
        message = str(exc)
        details.update({"status": "not_attempted", "reason": message,
                        "access": getattr(exc, "access_status", "disallowed" if "disallow" in message.lower() else "unverified"),
                        "robots_http_status": getattr(exc, "http_status", None),
                        "robots_content_type": getattr(exc, "content_type", None),
                        "robots_elapsed_ms": getattr(exc, "elapsed_ms", None)})
        details["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        _log("discovery_search", {"platform": adapter.platform.key, **details})
        return {**details, "urls": [], "titles": {}}
    details["request_attempted"] = True
    try:
        response = fetch_bounded_response(url, settings.max_response_bytes, timeout=_request_timeout(deadline, settings.discovery_search_timeout_seconds))
        details.update({"http_status": response.status_code, "content_type": response.content_type,
                        "response_bytes": len(response.body)})
        if response.status_code != 200:
            details.update({"status": "http_error", "reason": f"HTTP {response.status_code}"})
            details["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            _log("discovery_search", {"platform": adapter.platform.key, **details})
            return {**details, "urls": [], "titles": {}}
        media_type = (response.content_type or "").split(";", 1)[0].lower()
        if media_type not in ("text/html", "application/xhtml+xml"):
            details.update({"status": "parse_failed", "parser_status": "unexpected_content_type",
                            "reason": "Search response was not HTML."})
            details["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
            _log("discovery_search", {"platform": adapter.platform.key, **details})
            return {**details, "urls": [], "titles": {}}
        parsed = extract_candidate_urls(response.text, url, adapter.platform.key)
        details.update(parsed["counts"])
        details["candidate_urls_extracted"] = len(parsed["urls"])
        details["parser_status"] = "parsed_product_urls" if parsed["urls"] else "parsed_no_product_urls"
        details["status"] = "results_found" if parsed["urls"] else "no_product_urls"
        details["reason"] = None if parsed["urls"] else "No retailer product links were extracted from the HTML response."
        details["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        _log("discovery_search", {"platform": adapter.platform.key, **details})
        return {**details, "urls": parsed["urls"], "titles": parsed["titles"]}
    except (httpx.HTTPError, ValueError) as exc:
        response = getattr(exc, "response", None)
        details.update({"status": "request_failed", "reason": str(exc)[:180],
                        "http_status": response.status_code if response is not None else details["http_status"],
                        "content_type": response.headers.get("content-type") if response is not None else details["content_type"]})
        details["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        _log("discovery_search", {"platform": adapter.platform.key, **details})
        return {**details, "urls": [], "titles": {}}


def search_product_urls(adapter: PlatformAdapter, product: dict, deadline: float | None = None) -> dict:
    queries = build_search_queries(product, adapter.platform.key)
    if not queries:
        return {"attempts": [], "urls": [], "complete": False, "reason": "Product identity is insufficient to form a retailer query."}
    attempts = []
    urls = []
    titles = {}
    deadline_reached = False
    for query in queries:
        if deadline is not None and time.monotonic() >= deadline:
            deadline_reached = True
            break
        result = _search_attempt(adapter, query, deadline)
        attempts.append({key: value for key, value in result.items() if key not in ("urls", "titles")})
        urls.extend(result["urls"])
        titles.update(result.get("titles", {}))
        if urls:
            break
        if result["status"] not in ("no_product_urls",):
            break
    urls = list(dict.fromkeys(urls))
    successful = next((item for item in reversed(attempts) if item["status"] == "results_found"), None)
    complete = bool(successful and not successful.get("truncated") and not successful.get("pagination_links_seen"))
    return {"attempts": attempts, "urls": urls, "titles": titles, "complete": complete,
            "deadline_reached": deadline_reached,
            "reason": ("Overall discovery deadline reached before remaining search queries." if deadline_reached else
                       None if urls else (attempts[-1].get("reason") if attempts else "No query was generated."))}


def _xml_document(url: str, deadline: float | None = None) -> tuple[bytes, dict]:
    response = fetch_bounded_response(url, settings.max_sitemap_bytes, timeout=_request_timeout(deadline, 12.0))
    meta = {"url": _path_only(url), "http_status": response.status_code,
            "content_type": response.content_type, "response_bytes": len(response.body),
            "elapsed_ms": response.elapsed_ms}
    if response.status_code != 200:
        raise httpx.HTTPStatusError(f"Sitemap returned HTTP {response.status_code}.",
                                    request=httpx.Request("GET", url),
                                    response=httpx.Response(response.status_code, request=httpx.Request("GET", url),
                                                            headers={"content-type": response.content_type or ""}))
    data = response.body
    if urlparse(url).path.lower().endswith(".gz"):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as archive:
            data = archive.read(settings.max_sitemap_bytes + 1)
        if len(data) > settings.max_sitemap_bytes:
            raise ValueError("Expanded sitemap exceeds configured size limit.")
    return data, meta


def sitemap_product_urls(adapter: PlatformAdapter, deadline: float | None = None) -> tuple[list[str], bool, str, dict]:
    started = time.perf_counter()
    try:
        roots = permitted_sitemaps(adapter, deadline=deadline)
    except ValueError as exc:
        detail = {"status": "unavailable", "reason": str(exc), "pages_checked": 0,
                  "product_urls_extracted": 0, "limit_reached": False,
                  "requests": [], "elapsed_ms": int((time.perf_counter() - started) * 1000)}
        return [], False, f"Sitemap discovery unavailable: {str(exc)[:140]}", detail
    if not roots:
        detail = {"status": "unavailable", "reason": "No permitted sitemap was declared in robots.txt.",
                  "pages_checked": 0, "product_urls_extracted": 0, "limit_reached": False,
                  "requests": [], "elapsed_ms": int((time.perf_counter() - started) * 1000)}
        return [], False, "No permitted retailer sitemap was declared in the current robots file.", detail

    preferred_host = f"www.{adapter.platform.domains[0]}"
    roots.sort(key=lambda item: (0 if urlparse(item).hostname == preferred_host else 1, item))
    queue = list(roots)
    seen_sitemaps: set[str] = set()
    product_urls: set[str] = set()
    requests, errors = [], []
    processed = 0
    deadline_reached = False
    while queue and processed < settings.max_sitemap_files:
        if deadline is not None and time.monotonic() >= deadline:
            deadline_reached = True
            break
        sitemap = queue.pop(0)
        if sitemap in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap)
        processed += 1
        try:
            validate_permitted_page(sitemap, deadline=deadline)
            body, meta = _xml_document(sitemap, deadline)
            requests.append(meta)
            root = ET.fromstring(body)
        except (ValueError, httpx.HTTPError, ET.ParseError) as exc:
            response = getattr(exc, "response", None)
            errors.append({"url": _path_only(sitemap), "reason": str(exc)[:160],
                           "http_status": response.status_code if response is not None else None,
                           "content_type": response.headers.get("content-type") if response is not None else None})
            continue
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        if root_name == "sitemapindex":
            child_urls = [node.text.strip() for node in root.iter()
                          if node.tag.rsplit("}", 1)[-1].lower() == "loc" and node.text]
            queue.extend(url for url in child_urls if adapter.supports_url(url))
        else:
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1].lower() != "loc" or not node.text:
                    continue
                candidate_url = node.text.strip()
                if (adapter.supports_url(candidate_url) and urlparse(candidate_url).scheme == "https"
                        and is_product_page_url(adapter.platform.key, candidate_url)):
                    product_urls.add(candidate_url)
    deadline_reached = deadline_reached or bool(deadline is not None and queue and time.monotonic() >= deadline)
    limit_reached = bool(queue) and not deadline_reached
    complete = not limit_reached and not deadline_reached and not errors
    note_parts = []
    if limit_reached:
        note_parts.append("Sitemap traversal reached its configured file limit.")
    if errors:
        note_parts.append("Some declared sitemap pages could not be checked.")
    if deadline_reached:
        note_parts.append("Overall discovery deadline reached; remaining sitemap work was stopped.")
    detail = {"status": "complete" if complete else "incomplete", "pages_checked": processed,
              "product_urls_extracted": len(product_urls), "limit_reached": limit_reached,
              "requests": requests, "errors": errors, "deadline_reached": deadline_reached,
              "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    _log("discovery_sitemap", {"platform": adapter.platform.key, **detail})
    return sorted(product_urls), complete, " ".join(note_parts), detail


def _candidate_score(url: str, product: dict, platform_key: str | None = None, title: str | None = None) -> float:
    path = urlparse(url).path.lower()
    normalized_url = normalize_key(path)
    identifiers = product.get("identifiers") or {}
    identity = [identifiers.get("gtin"), identifiers.get("mpn")]
    if platform_key and platform_key == product.get("origin_platform"):
        identity.append(identifiers.get("sku"))
    for value in identity:
        token = normalize_key(str(value or ""))
        if len(token) >= 5 and token in normalized_url:
            return 1.0
    attrs = _search_attributes(product)
    words = [normalize_key(word) for word in re.findall(r"[a-z0-9]+", " ".join([attrs["family"], *attrs["storage"], *attrs["color"]]).lower())]
    words = [word for word in words if len(word) >= 3 and word not in STOP_WORDS]
    source_tokens = {normalize_key(token) for token in re.findall(r"[a-z0-9]+", str(product.get("title") or "").lower())}
    modifiers = {"pro", "max", "air", "plus", "mini", "ultra", "fold", "flip", "lite", "edge"}
    path_tokens = {normalize_key(token) for token in re.findall(r"[a-z0-9]+", path)}
    source_modifiers = source_tokens & modifiers
    unexpected_modifiers = (path_tokens & modifiers) - source_modifiers
    if unexpected_modifiers:
        return -1.0 - len(unexpected_modifiers)
    score = sum(1 for word in set(words) if word in normalized_url) / len(set(words)) if words else 0.0
    if title:
        title_tokens = {normalize_key(token) for token in re.findall(r"[a-z0-9]+", title.lower())}
        score += (sum(1 for word in set(words) if word in title_tokens) / max(len(set(words)), 1)) * 2
        unexpected_title_modifiers = (title_tokens & modifiers) - source_modifiers
        if unexpected_title_modifiers:
            score -= 2.0 + len(unexpected_title_modifiers)
    return score


def discover_platform_candidates(platform_key: str, source_product: dict, manual_urls: list[str], deadline: float | None = None) -> dict:
    adapter = ADAPTERS[platform_key]
    started = time.perf_counter()
    deadline = deadline if deadline is not None else time.monotonic() + settings.discovery_overall_timeout_seconds
    attributes = _search_attributes(source_product)
    _log("discovery_start", {"platform": platform_key, "attributes": attributes,
                             "source_platform": source_product.get("origin_platform")})

    def run_sitemap():
        try:
            return sitemap_product_urls(adapter, deadline)
        except Exception as exc:
            return [], False, f"Sitemap discovery unavailable: {str(exc)[:140]}", {
                "status": "unavailable", "reason": str(exc)[:180], "pages_checked": 0,
                "product_urls_extracted": 0, "limit_reached": False, "requests": [], "errors": []}

    def run_search():
        return search_product_urls(adapter, source_product, deadline)

    with ThreadPoolExecutor(max_workers=2) as pool:
        sitemap_future = pool.submit(run_sitemap)
        search_future = pool.submit(run_search)
        sitemap_urls, sitemap_complete, sitemap_note, sitemap_details = sitemap_future.result()
        try:
            search_result = search_future.result()
        except Exception as exc:
            search_result = {"attempts": [], "urls": [], "complete": False, "reason": str(exc)[:180]}

    notes = [note for note in (sitemap_note, search_result.get("reason")) if note]
    search_urls = search_result["urls"]
    search_titles = search_result.get("titles", {})
    ranked_search = sorted(search_urls, key=lambda url: (_candidate_score(url, source_product, platform_key, search_titles.get(url)), url), reverse=True)
    ranked_sitemap = sorted(sitemap_urls, key=lambda url: (_candidate_score(url, source_product, platform_key), url), reverse=True)
    manual_urls = list(dict.fromkeys(manual_urls))
    all_urls = list(dict.fromkeys([*manual_urls, *ranked_search, *ranked_sitemap]))
    all_urls = [url for url in all_urls if url != source_product.get("origin_url")]
    cap = settings.max_discovery_candidates
    # Rank result URLs by model family and exact variant terms before spending
    # the bounded product-page fetch budget.
    if len(all_urls) > cap:
        search_set = set(search_urls)
        all_urls = sorted(all_urls, key=lambda candidate_url: (
            2 if candidate_url in manual_urls else 1 if candidate_url in search_set else 0,
            _candidate_score(candidate_url, source_product, platform_key, search_titles.get(candidate_url)),
            candidate_url), reverse=True)
    selected = all_urls[:cap]
    selection = {"manual_urls": len(manual_urls), "search_urls": len(search_urls),
                 "sitemap_urls": len(sitemap_urls), "unique_candidates_considered": len(all_urls),
                 "selected_for_fetch": len(selected), "rejected_by_candidate_limit": max(0, len(all_urls) - len(selected))}
    candidates, candidate_diagnostics = [], []
    candidate_page_failures = 0
    match_rejections = 0
    price_verified_count = 0
    exact_price_verified_count = 0

    def check_candidate(candidate_url: str):
        record = {"url": _path_only(candidate_url), "request_attempted": False,
                  "http_status": None, "content_type": None, "elapsed_ms": 0,
                  "parse_status": "not_run", "match_classification": None,
                  "match_evidence": [], "price_status": "not_checked", "price_evidence": None}
        candidate_started = time.perf_counter()
        page_failures = match_rejections = price_verified = exact_price_verified = 0
        try:
            target_adapter = adapter_for_url(candidate_url)
            if not target_adapter or target_adapter.platform.key != platform_key or not is_product_page_url(platform_key, candidate_url):
                record.update({"outcome": "rejected_non_product_url", "reason": "Candidate URL did not match a retailer product-page route."})
                match_rejections += 1
                _log("discovery_candidate", {"platform": platform_key, **record})
                return record, None, page_failures, match_rejections, price_verified, exact_price_verified
            validate_permitted_page(candidate_url, deadline=deadline)
            record["request_attempted"] = True
            response = fetch_bounded_response(candidate_url, settings.max_response_bytes,
                                              timeout=_request_timeout(deadline, settings.discovery_candidate_timeout_seconds))
            record.update({"http_status": response.status_code, "content_type": response.content_type,
                           "elapsed_ms": response.elapsed_ms})
            if response.status_code != 200:
                record.update({"outcome": "page_fetch_failed", "reason": f"HTTP {response.status_code}"})
                page_failures += 1
                _log("discovery_candidate", {"platform": platform_key, **record})
                return record, None, page_failures, match_rejections, price_verified, exact_price_verified
            media_type = (response.content_type or "").split(";", 1)[0].lower()
            if media_type not in ("text/html", "application/xhtml+xml"):
                record.update({"outcome": "page_parse_failed", "parse_status": "unexpected_content_type",
                               "reason": "Product page response was not HTML."})
                page_failures += 1
                _log("discovery_candidate", {"platform": platform_key, **record})
                return record, None, page_failures, match_rejections, price_verified, exact_price_verified
            data = target_adapter.extract(response.text, candidate_url)
            record["parse_status"] = "product_data_extracted"
            record["product_title"] = data.get("title")
            record["product_brand"] = data.get("brand")
            record["product_model"] = data.get("model")
            record["product_identifiers"] = data.get("identifiers", {})
            record["product_specs"] = data.get("specs", {})
            match = match_product(source_product, data)
            record.update({"match_classification": match["classification"], "match_evidence": match["evidence"],
                           "match_missing": match["missing"], "match_conflicts": match["conflicts"]})
            if match["classification"] == "non_match":
                record.update({"outcome": "candidate_verification_failed", "reason": "Product identity or variant did not match."})
                match_rejections += 1
                _log("discovery_candidate", {"platform": platform_key, **record})
                return record, None, page_failures, match_rejections, price_verified, exact_price_verified

            evidence = data.get("evidence") or {}
            evidence_source = evidence.get("source") if isinstance(evidence, dict) else None
            price = data.get("price")
            currency = data.get("currency")
            price_type = data.get("price_type")
            price_is_verified = bool(price is not None and currency == "INR" and price_type == "selling"
                                     and evidence_source and (evidence_source == "json-ld" or evidence_source.startswith("html-selector:")))
            if price_is_verified:
                price_verified += 1
                if match["classification"] == "exact":
                    exact_price_verified += 1
                record.update({"price_status": "verified_current_selling_price", "price_evidence": evidence_source,
                               "price": str(price), "currency": currency, "price_type": price_type})
            else:
                record.update({"price_status": "unavailable_or_unverified", "price_evidence": evidence_source,
                               "price_present": price is not None, "price_currency": currency,
                               "price_type": price_type})
            candidate = {**data, "url": candidate_url, "match": match,
                         "price": price if price_is_verified else None,
                         "currency": currency if price_is_verified else None,
                         "price_type": "selling" if price_is_verified else "unknown"}
            if match["classification"] in ("exact", "probable", "uncertain"):
                record["outcome"] = "candidate_accepted"
            else:
                record["outcome"] = "candidate_verification_failed"
                match_rejections += 1
                candidate = None
            _log("discovery_candidate", {"platform": platform_key, **record})
            return record, candidate, page_failures, match_rejections, price_verified, exact_price_verified
        except (ValueError, httpx.HTTPError) as exc:
            response = getattr(exc, "response", None)
            record.update({"elapsed_ms": int((time.perf_counter() - candidate_started) * 1000),
                           "outcome": "page_check_failed", "reason": str(exc)[:180],
                           "access": getattr(exc, "access_status", None),
                           "robots_http_status": getattr(exc, "http_status", None),
                           "robots_content_type": getattr(exc, "content_type", None),
                           "http_status": response.status_code if response is not None else record["http_status"],
                           "content_type": response.headers.get("content-type") if response is not None else record["content_type"]})
            page_failures += 1
            _log("discovery_candidate", {"platform": platform_key, **record})
            return record, None, page_failures, match_rejections, price_verified, exact_price_verified

    candidate_workers = max(1, min(settings.discovery_candidate_concurrency, len(selected)))
    with ThreadPoolExecutor(max_workers=candidate_workers) as pool:
        for record, candidate, failed, rejected, priced, exact_priced_count in pool.map(check_candidate, selected):
            candidate_diagnostics.append(record)
            candidate_page_failures += failed
            match_rejections += rejected
            price_verified_count += priced
            exact_price_verified_count += exact_priced_count
            if candidate is not None:
                candidates.append(candidate)

    exact = [candidate for candidate in candidates if candidate["match"]["classification"] == "exact"]
    exact_priced = [candidate for candidate in exact if candidate.get("price") is not None]
    similar = [candidate for candidate in candidates if candidate["match"]["classification"] in ("probable", "uncertain")]
    deadline_reached = time.monotonic() >= deadline
    selected_all_sources = len(selected) == len(all_urls)
    search_complete = bool(search_result.get("complete"))
    source_complete = bool(not deadline_reached and selected_all_sources and (sitemap_complete or search_complete))
    if exact_priced:
        status, outcome = "exact_match_found", "exact_product_price_verified"
    elif exact:
        status, outcome = "price_unavailable", "exact_product_price_unavailable"
    elif similar:
        status, outcome = "similar_product_found", "similar_product_found"
    elif not source_complete:
        status, outcome = "could_not_check", "discovery_incomplete"
    elif candidate_page_failures or match_rejections:
        status, outcome = "could_not_check", "candidate_verification_failed"
    else:
        status, outcome = "no_match_found", "no_match_found_after_complete_discovery"
    incomplete_reasons = []
    if not search_result.get("attempts") or not any(item.get("status") == "results_found" for item in search_result.get("attempts", [])):
        incomplete_reasons.append("No usable product URLs came from permitted retailer search.")
    if not sitemap_complete:
        incomplete_reasons.append(sitemap_note or "Permitted sitemap discovery was incomplete.")
    if selection["rejected_by_candidate_limit"]:
        incomplete_reasons.append("Some candidate URLs were not fetched because of the configured candidate limit.")
    if deadline_reached:
        incomplete_reasons.append("Overall discovery deadline reached; remaining retailer checks were stopped.")
    if candidate_page_failures:
        incomplete_reasons.append(f"{candidate_page_failures} candidate product page(s) could not be checked.")
    if match_rejections:
        incomplete_reasons.append(f"{match_rejections} candidate(s) failed exact product verification.")
    if notes and status not in ("no_match_found",):
        message = " ".join(notes + incomplete_reasons)
    elif incomplete_reasons and status != "no_match_found":
        message = " ".join(incomplete_reasons)
    else:
        message = None
    diagnostics = {"attributes": attributes, "search": {"queries": build_search_queries(source_product, platform_key),
                    "attempts": search_result.get("attempts", []), "candidate_urls_extracted": len(search_urls),
                    "complete": search_complete},
                   "sitemap": sitemap_details,
                   "candidates": {**selection, "pages_checked": sum(1 for item in candidate_diagnostics if item["request_attempted"] and item["http_status"] == 200),
                                  "pages_failed": candidate_page_failures, "match_rejected": match_rejections,
                                  "exact_matches": len(exact), "selling_prices_verified": price_verified_count,
                                  "exact_prices_verified": exact_price_verified_count,
                                  "details": candidate_diagnostics},
                   "outcome": outcome, "complete": source_complete and not candidate_page_failures and not selection["rejected_by_candidate_limit"] and not deadline_reached,
                   "deadline_reached": deadline_reached, "deadline_seconds": settings.discovery_overall_timeout_seconds,
                   "elapsed_ms": int((time.perf_counter() - started) * 1000)}
    _log("discovery_platform_complete", {"platform": platform_key, **diagnostics})
    return {"status": status, "message": message, "candidates": candidates, "diagnostics": diagnostics}
