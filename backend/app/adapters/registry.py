from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Platform:
    key: str
    name: str
    domains: tuple[str, ...]
    discovery_status: str = "configured_unverified"
    discovery_note: str = "No verified, permitted candidate-discovery path is configured."


PLATFORMS = (
    Platform("amazon_india", "Amazon India", ("amazon.in",), discovery_note="Search access rules could not be verified; automated search fails closed and permitted sitemap discovery is attempted."),
    Platform("flipkart", "Flipkart", ("flipkart.com",), discovery_note="Robots disallow /search?; permitted sitemap discovery and user-provided listing URLs are used."),
    Platform("shopsy", "Shopsy", ("shopsy.in",), discovery_note="Robots disallow /search?; permitted sitemap discovery and user-provided listing URLs are used."),
    Platform("myntra", "Myntra", ("myntra.com",), discovery_note="Robots/access rules could not be verified; search and sitemap access fail closed until rules can be read."),
    Platform("meesho", "Meesho", ("meesho.com",), discovery_note="Robots disallow /search; permitted sitemap discovery and user-provided listing URLs are used."),
    Platform("ajio", "AJIO", ("ajio.com",), discovery_note="Robots disallow /search; permitted sitemap discovery and user-provided listing URLs are used."),
    Platform("croma", "Croma", ("croma.com",), discovery_note="Robots disallow /searchB and ?q= search URLs; permitted sitemap discovery and user-provided listing URLs are used."),
)


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _walk_jsonld(value: Any):
    if isinstance(value, list):
        for entry in value:
            yield from _walk_jsonld(entry)
    elif isinstance(value, dict):
        graph = value.get("@graph")
        if graph:
            yield from _walk_jsonld(graph)
        typ = value.get("@type", [])
        types = typ if isinstance(typ, list) else [typ]
        if any(str(t).rsplit("/", 1)[-1].rsplit("#", 1)[-1].lower() == "product" for t in types):
            yield value
        for key in ("mainEntity", "item", "offers"):
            child = value.get(key)
            if isinstance(child, (dict, list)):
                yield from _walk_jsonld(child)


def _first(value, *keys):
    if not isinstance(value, dict):
        return None
    for key in keys:
        item = value.get(key)
        if isinstance(item, dict):
            item = item.get("name") or item.get("value")
        if isinstance(item, list):
            item = next((x for x in item if isinstance(x, str)), None)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _parse_price(offers: Any):
    entries = offers if isinstance(offers, list) else [offers]
    parsed = []
    for offer in entries:
        if not isinstance(offer, dict):
            continue
        kinds = offer.get("@type", [])
        kinds = kinds if isinstance(kinds, list) else [kinds]
        normalized_kinds = {str(kind).rsplit("/", 1)[-1].lower() for kind in kinds}
        if "aggregateoffer" in normalized_kinds:
            continue
        raw = offer.get("price")
        try:
            price = Decimal(str(raw)).quantize(Decimal("0.01"))
            if not price.is_finite() or price <= 0:
                continue
        except (InvalidOperation, ValueError, TypeError):
            continue
        currency = str(offer.get("priceCurrency") or "").upper()
        if re.fullmatch(r"[A-Z]{3}", currency):
            parsed.append((price, currency))
    # Multiple different offers may represent sellers or variants. Without
    # per-offer variant binding, do not call the first one a verified price.
    distinct = set(parsed)
    return next(iter(distinct)) if len(distinct) == 1 else (None, None)


def _parse_price_text(value: str):
    match = re.search(r"(?:₹|INR\s*)?([0-9][0-9,]*(?:\.\d{1,2})?)", value or "")
    if not match:
        return None
    try:
        price = Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        return price if price.is_finite() and price > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _html_selling_price(soup: BeautifulSoup):
    # These selectors target current-price containers only. MRP/strike-through
    # selectors are intentionally excluded so a list price cannot become a sale
    # price by accident.
    selectors = (
        ('meta[itemprop="price"]', "content"),
        ("#corePriceDisplay_desktop_feature_div .priceToPay .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div .apex-pricetopay-value .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div > .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen", None),
        ("#priceblock_dealprice", None),
        ("#priceblock_ourprice", None),
        ("[data-testid='price']", None),
    )
    for selector, attribute in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        raw = node.get(attribute) if attribute else node.get_text(" ", strip=True)
        price = _parse_price_text(str(raw))
        if price is not None:
            return price, "INR", f"html-selector:{selector}"
    return None, None, None


def extract_product(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    product = None
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(node.string or node.get_text())
            product = next(_walk_jsonld(parsed), None)
        except (json.JSONDecodeError, TypeError):
            continue
        if product:
            break
    title = _first(product or {}, "name")
    if not title:
        og = soup.find("meta", property="og:title")
        title = (og.get("content") if og else None) or (soup.title.string if soup.title else None)
    if not title:
        raise ValueError("Product title was not found in structured data or page metadata.")
    offers = (product or {}).get("offers")
    if isinstance(offers, list):
        offers = offers[0] if len(offers) == 1 else {}
    price, currency = _parse_price(offers)
    price_evidence = "json-ld"
    if price is None:
        price, currency, selector = _html_selling_price(soup)
        if selector:
            price_evidence = selector
    availability = "unknown"
    if isinstance(offers, dict):
        avail = str(offers.get("availability", "")).lower()
        if "instock" in avail:
            availability = "in_stock"
        elif "outofstock" in avail or "soldout" in avail:
            availability = "out_of_stock"
        elif "preorder" in avail:
            availability = "preorder"
    identifiers = {}
    for field, keys in {"sku": ("sku",), "mpn": ("mpn",), "gtin": ("gtin13", "gtin14", "gtin12", "gtin8", "gtin")}.items():
        val = _first(product or {}, *keys)
        if val:
            identifiers[field] = val
    raw_brand = (product or {}).get("brand")
    brand = raw_brand.strip() if isinstance(raw_brand, str) else _first(raw_brand or {}, "name")
    image = (product or {}).get("image")
    if isinstance(image, list):
        image = next((item for item in image if isinstance(item, str)), None)
    elif isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        og_image = soup.find("meta", property="og:image")
        image = og_image.get("content") if og_image else None
    if image and urlparse(str(image)).scheme.lower() != "https":
        image = None
    model = _first(product or {}, "model") or identifiers.get("mpn")
    specs = {}
    additional = (product or {}).get("additionalProperty", [])
    if isinstance(additional, dict):
        additional = [additional]
    if isinstance(additional, list):
        for prop in additional:
            if isinstance(prop, dict) and prop.get("name") and prop.get("value"):
                specs[str(prop["name"]).strip().lower()] = str(prop["value"]).strip()
    return {"title": str(title).strip()[:500], "brand": brand, "model": model, "image_url": image,
            "identifiers": identifiers, "specs": specs, "price": price,
            "currency": currency, "availability": availability,
            "price_type": "selling" if price is not None else "unknown",
            "evidence": {"source": price_evidence if price is not None else ("json-ld" if product else "page-metadata"), "url": url}}


@dataclass(frozen=True)
class PlatformAdapter:
    platform: Platform
    version: str = "1"

    def supports_url(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
            return any(host == d or host.endswith("." + d) for d in self.platform.domains)
        except ValueError:
            return False

    def extract(self, html: str, url: str) -> dict:
        if not self.supports_url(url):
            raise ValueError("URL host does not belong to this retailer adapter.")
        result = extract_product(html, url)
        result["platform"] = self.platform.key
        result["adapter_version"] = self.version
        return result


class AmazonIndiaAdapter(PlatformAdapter):
    pass


class FlipkartAdapter(PlatformAdapter):
    pass


class ShopsyAdapter(PlatformAdapter):
    pass


class MyntraAdapter(PlatformAdapter):
    pass


class MeeshoAdapter(PlatformAdapter):
    pass


class AjioAdapter(PlatformAdapter):
    pass


class CromaAdapter(PlatformAdapter):
    pass


ADAPTERS = {
    "amazon_india": AmazonIndiaAdapter(PLATFORMS[0]),
    "flipkart": FlipkartAdapter(PLATFORMS[1]),
    "shopsy": ShopsyAdapter(PLATFORMS[2]),
    "myntra": MyntraAdapter(PLATFORMS[3]),
    "meesho": MeeshoAdapter(PLATFORMS[4]),
    "ajio": AjioAdapter(PLATFORMS[5]),
    "croma": CromaAdapter(PLATFORMS[6]),
}


def adapter_for_url(url: str) -> PlatformAdapter | None:
    return next((a for a in ADAPTERS.values() if a.supports_url(url)), None)
