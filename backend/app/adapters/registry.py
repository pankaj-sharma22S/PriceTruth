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
    discovery_note: str = "Candidate discovery searches retailer product listings."


PLATFORMS = (
    Platform("amazon_india", "Amazon India", ("amazon.in",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("flipkart", "Flipkart", ("flipkart.com",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("shopsy", "Shopsy", ("shopsy.in",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("myntra", "Myntra", ("myntra.com",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("meesho", "Meesho", ("meesho.com",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("ajio", "AJIO", ("ajio.com",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
    Platform("croma", "Croma", ("croma.com",), discovery_note="Retailer search and product extraction with structured candidate discovery."),
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
    distinct = set(parsed)
    return next(iter(distinct)) if len(distinct) == 1 else (None, None)


def _parse_price_text(value: str):
    if not value:
        return None
    # 1. Match amount immediately following currency symbol (avoids catching ratings or discount %)
    curr_match = re.search(r"(?:₹|INR)\s*([0-9][0-9,]*(?:\.\d{1,2})?)", value)
    if curr_match:
        try:
            price = Decimal(curr_match.group(1).replace(",", "")).quantize(Decimal("0.01"))
            return price if price.is_finite() and price > 0 else None
        except (InvalidOperation, ValueError):
            pass
    # 2. General pattern matching standalone price
    match = re.search(r"(?:^|[\s(])([0-9][0-9,]*(?:\.\d{1,2})?)(?:$|[\s)])", value)
    if not match:
        match = re.search(r"([0-9][0-9,]*(?:\.\d{1,2})?)", value)
    if not match:
        return None
    try:
        price = Decimal(match.group(1).replace(",", "")).quantize(Decimal("0.01"))
        return price if price.is_finite() and price > 0 else None
    except (InvalidOperation, ValueError):
        return None


def _html_selling_price(soup: BeautifulSoup):
    selectors = (
        ('meta[itemprop="price"]', "content"),
        # Flipkart and Shopsy price classes
        ("div.Nx9bqj.CxhGGd", None),
        ("div.Nx9bqj", None),
        ("div._30jeq3._16Jk6d", None),
        ("div._30jeq3", None),
        ("div._16Jk6d", None),
        # Amazon price classes
        ("span#apex-pricetopay-accessibility-label", None),
        ("#corePrice_mobile_feature_div .priceToPay .a-price-whole", None),
        ("#corePrice_mobile_feature_div .a-price .a-offscreen", None),
        ("#corePriceDisplay_desktop_feature_div .priceToPay .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div .apex-pricetopay-value .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div > .a-price-whole", None),
        ("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen", None),
        (".a-price.aok-align-center .a-offscreen", None),
        ("span.a-price span.a-offscreen", None),
        ("#priceblock_dealprice", None),
        ("#priceblock_ourprice", None),
        # AJIO price classes
        ("span.prod-sp", None),
        ("span.price-current", None),
        (".prod-price-section .prod-sp", None),
        # Croma price classes
        ("span.amount", None),
        ("span.pdp-cp-price", None),
        ("span.main-product-price", None),
        ("span.new-price", None),
        # Myntra price classes
        ("strong.pdp-price", None),
        ("span.pdp-price strong", None),
        ("span.pdp-price", None),
        # Meesho price classes
        ("h4[class*='Text__StyledText']", None),
        ("span[class*='Price']", None),
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


def _html_mrp_price(soup: BeautifulSoup):
    selectors = (
        # Amazon MRP / List price
        ("span.a-price.a-text-price span.a-offscreen", None),
        ("span.basisPrice .a-offscreen", None),
        ("#corePriceDisplay_desktop_feature_div span.a-price.a-text-price span[aria-hidden='true']", None),
        ("span.a-price.a-text-price", None),
        # Flipkart and Shopsy MRP
        ("div.yRaY8j", None),
        ("div._3I9_wc._2p6XSc", None),
        ("div._3I9_wc", None),
        ("div._2p6XSc", None),
        # Myntra MRP
        ("span.pdp-mrp", None),
        ("span.pdp-mrp s", None),
        # AJIO MRP
        ("span.prod-cp", None),
        ("span.original-price", None),
        # Croma MRP
        ("span.old-price", None),
        ("span.pdp-old-price", None),
        ("span.cp-price", None),
        # Meesho MRP
        ("span[class*='mrp']", None),
        ("span[class*='Mrp']", None),
        ("p[class*='mrp']", None),
    )
    for selector, attribute in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        raw = node.get(attribute) if attribute else node.get_text(" ", strip=True)
        price = _parse_price_text(str(raw))
        if price is not None:
            return price, f"html-selector:{selector}"
    return None, None


def _html_discount_text(soup: BeautifulSoup):
    selectors = (
        "span.savingPriceOverride",
        "div.UkUFwK span",
        "div._3Ay6Sb span",
        "span.pdp-discount",
        "span.prod-discnt",
        "span.discount",
        "p[class*='Discount']",
        "span[class*='Discount']"
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        text = node.get_text(" ", strip=True)
        match = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", text)
        if match:
            try:
                return Decimal(match.group(1))
            except Exception:
                pass
    return None


def _determine_stock_availability(soup: BeautifulSoup, html: str, offers: dict, selling_price: Decimal | None):
    # 1. Structured JSON-LD evidence
    if isinstance(offers, dict):
        avail = str(offers.get("availability", "")).lower()
        if "outofstock" in avail or "soldout" in avail:
            return "out_of_stock", "json-ld:OutOfStock"
        if "instock" in avail:
            return "in_stock", "json-ld:InStock"
        if "preorder" in avail:
            return "preorder", "json-ld:PreOrder"
        if "comingsoon" in avail:
            return "coming_soon", "json-ld:ComingSoon"

    # 2. Positive Out of Stock evidence (only mark out of stock when positive evidence exists)
    oos_selectors = (
        "div#outOfStock",
        "div#availability .a-color-price",
        "div._16FRp0",
        "div._1V4nnK",
        ".prod-out-of-stock",
        ".pdp-out-of-stock",
        "[data-testid='out-of-stock']",
    )
    for selector in oos_selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text(" ", strip=True).lower()
            if any(k in text for k in ("out of stock", "currently unavailable", "sold out", "temporarily unavailable")):
                return "out_of_stock", f"positive-selector:{selector}"

    # Target specific availability containers
    avail_box = soup.select_one("#availability") or soup.select_one(".pdp-action-container") or soup.select_one(".product-action")
    if avail_box:
        box_text = avail_box.get_text(" ", strip=True).lower()
        if "currently unavailable" in box_text or "out of stock" in box_text or "sold out" in box_text:
            return "out_of_stock", "positive-container:availability"
        if "in stock" in box_text or "left in stock" in box_text:
            return "in_stock", "positive-container:in-stock"

    # Check preorder / coming soon text
    if any(k in html.lower()[:15000] for k in ("available for pre-order", "pre-order now", "preorder now")):
        return "preorder", "keyword:preorder"
    if "coming soon" in html.lower()[:15000]:
        return "coming_soon", "keyword:coming_soon"

    # 3. Positive In Stock evidence
    in_stock_selectors = (
        "#add-to-cart-button",
        "#buy-now-button",
        "button[aria-label*='Add to Cart']",
        "button[aria-label*='Buy Now']",
        "button._2KpZ6l._2U9uOA._3v1-ww",
        "button.pdp-add-to-bag",
        "button.btn-add-to-cart",
        "div.product-buy-now",
    )
    for selector in in_stock_selectors:
        if soup.select_one(selector):
            return "in_stock", f"action-button:{selector}"

    # 4. Default: If selling price is extracted and there is no negative signal, it is available
    if selling_price is not None and selling_price > 0:
        return "in_stock", "inferred:selling-price-present"

    return "unknown", "unknown"


def extract_product(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    product = None
    decoder = json.JSONDecoder()
    for node in soup.select('script[type="application/ld+json"]'):
        text = (node.string or node.get_text() or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
            product = next(_walk_jsonld(parsed), None)
        except (json.JSONDecodeError, TypeError):
            idx = 0
            while idx < len(text):
                try:
                    obj, end = decoder.raw_decode(text[idx:])
                    product = next(_walk_jsonld(obj), None)
                    if product:
                        break
                    idx += end
                    while idx < len(text) and text[idx] in " \t\r\n,;":
                        idx += 1
                except Exception:
                    break
        if product:
            break

    amazon_title_node = soup.find(id="productTitle")
    amazon_title = amazon_title_node.get_text(" ", strip=True) if amazon_title_node else None
    title = amazon_title or _first(product or {}, "name")
    if not title:
        og = soup.find("meta", property="og:title")
        title = (og.get("content") if og else None) or (soup.title.string if soup.title else None)
    if not title:
        raise ValueError("Product title was not found in structured data or page metadata.")
    title = str(title).strip()[:500]

    offers = (product or {}).get("offers")
    if isinstance(offers, list):
        offers = offers[0] if len(offers) == 1 else {}
    
    price, currency = _parse_price(offers)
    price_evidence = "json-ld"
    if price is None:
        price, currency, selector = _html_selling_price(soup)
        if selector:
            price_evidence = selector

    mrp, mrp_evidence = _html_mrp_price(soup)
    discount_pct = _html_discount_text(soup)

    identifiers = {}
    for field, keys in {"sku": ("sku",), "mpn": ("mpn",), "gtin": ("gtin13", "gtin14", "gtin12", "gtin8", "gtin")}.items():
        val = _first(product or {}, *keys)
        if val:
            identifiers[field] = val
    
    raw_brand = (product or {}).get("brand")
    brand = raw_brand.strip() if isinstance(raw_brand, str) else _first(raw_brand or {}, "name")
    retailer_names = {"shopsy", "flipkart", "amazon", "amazon india", "meesho", "croma", "ajio", "myntra"}
    if not brand or brand.lower().strip() in retailer_names:
        manufacturer = _first(product or {}, "manufacturer")
        if manufacturer and manufacturer.lower().strip() not in retailer_names:
            brand = manufacturer
        else:
            title_parts = title.split()
            if title_parts and title_parts[0].lower() not in {"buy", "the", "new", "online"}:
                candidate_brand = title_parts[0].strip(",.-")
                if candidate_brand.lower() not in retailer_names:
                    brand = candidate_brand
    
    brand_canonical = {
        "iphone": "Apple", "ipad": "Apple", "macbook": "Apple", "airpods": "Apple",
        "galaxy": "Samsung", "pixel": "Google", "playstation": "Sony", "xbox": "Microsoft",
        "redmi": "Xiaomi", "poco": "Xiaomi"
    }
    if brand and brand.lower().strip() in brand_canonical:
        brand = brand_canonical[brand.lower().strip()]

    # Comprehensive image extraction
    image = (product or {}).get("image")
    if isinstance(image, list):
        image = next((item for item in image if isinstance(item, str) and item.strip()), None)
    elif isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    if not image:
        meta_tags = (
            ("meta", {"property": "og:image"}),
            ("meta", {"name": "og:image"}),
            ("meta", {"name": "twitter:image"}),
            ("meta", {"property": "twitter:image"}),
            ("meta", {"name": "twitter:image:src"}),
            ("meta", {"itemprop": "image"}),
        )
        for m_tag, m_attrs in meta_tags:
            node = soup.find(m_tag, m_attrs)
            if node and node.get("content"):
                image = node.get("content").strip()
                break
    if not image:
        landing_img = soup.find("img", id="landingImage") or soup.find("img", id="imgBlkFront") or soup.find("img", id="main-image")
        if landing_img:
            image = landing_img.get("data-old-hires") or landing_img.get("src")
            if not image and landing_img.get("data-a-dynamic-image"):
                try:
                    dyn = json.loads(landing_img.get("data-a-dynamic-image"))
                    if isinstance(dyn, dict) and dyn:
                        image = next(iter(dyn.keys()))
                except Exception:
                    pass
    if image and isinstance(image, str):
        image = image.strip()
        if image.startswith("//"):
            image = "https:" + image
        elif image.startswith("http://"):
            image = "https://" + image[7:]
        if urlparse(image).scheme.lower() not in ("http", "https"):
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

    # Retailer-specific embedded state fallback (Myntra window.__myx)
    if "myntra.com" in url or price is None or not brand:
        idx = html.find("window.__myx = ")
        if idx != -1:
            try:
                sub = html[idx + len("window.__myx = "):]
                myx_obj, _ = decoder.raw_decode(sub)
                pdp = myx_obj.get("pdpData", {})
                p_info = pdp.get("price", {})
                if price is None:
                    p_val = p_info.get("discounted") or p_info.get("mrp")
                    if p_val:
                        price = Decimal(str(p_val))
                        currency = "INR"
                        price_evidence = "script:myx"
                if mrp is None and p_info.get("mrp"):
                    mrp = Decimal(str(p_info.get("mrp")))
                    mrp_evidence = "script:myx"
                if discount_pct is None and pdp.get("discount", {}).get("label"):
                    disc_match = re.search(r"(\d+)\s*%", pdp["discount"]["label"])
                    if disc_match:
                        discount_pct = Decimal(disc_match.group(1))
                if not brand and pdp.get("brand", {}).get("name"):
                    brand = pdp["brand"]["name"]
                if pdp.get("name") and (not title or title.lower().startswith("buy ")):
                    title = f"{brand or ''} {pdp['name']}".strip()
                if pdp.get("inStock") is not None:
                    avail_override = "in_stock" if pdp.get("inStock") else "out_of_stock"
                    offers["availability"] = "http://schema.org/InStock" if pdp.get("inStock") else "http://schema.org/OutOfStock"
            except Exception:
                pass

    # Flipkart / Shopsy state parsing (__NEXT_DATA__ and window.__INITIAL_STATE__)
    if "flipkart.com" in url or "shopsy.in" in url:
        f_pricing = None
        f_mrp = None
        f_disc = None
        f_img = None
        used_evidence = None

        # 1. Next.js __NEXT_DATA__ (Shopsy and modern Flipkart)
        next_tag = soup.find("script", id="__NEXT_DATA__")
        if next_tag:
            try:
                raw_txt = (next_tag.string or next_tag.text or "").strip()
                if raw_txt:
                    next_obj = json.loads(raw_txt)
                    p_state = next_obj.get("props", {}).get("pageProps", {}).get("initialState", {}).get("pageData", {})
                    resp = p_state.get("RESPONSE", {})
                    p_ctx = resp.get("pageData", {}).get("pageContext", {})
                    pricing = p_ctx.get("pricing") or {}

                    fp = pricing.get("finalPrice") or {}
                    fp_val = fp.get("value") or fp.get("decimalValue")
                    if fp_val:
                        f_pricing = Decimal(str(fp_val))
                        used_evidence = "script:next_data"

                    m_val = pricing.get("mrp")
                    if isinstance(m_val, dict):
                        m_val = m_val.get("value") or m_val.get("decimalValue")
                    if m_val:
                        f_mrp = Decimal(str(m_val))

                    disc = pricing.get("totalDiscount")
                    if disc is not None:
                        f_disc = Decimal(str(disc))

                    img_tpl = p_ctx.get("imageUrl")
                    if img_tpl:
                        f_img = img_tpl.replace("{@width}", "800").replace("{@height}", "800").replace("{@quality}", "80")

                    # Check slots fallback if pageContext had no pricing
                    if not f_pricing:
                        for slot in resp.get("slots", []):
                            widget_val = slot.get("widget", {}).get("data", {})
                            parent_p = widget_val.get("parentProduct", {}).get("value", {})
                            w_pricing = parent_p.get("pricing", {})
                            w_fp = w_pricing.get("finalPrice", {})
                            w_val = w_fp.get("value") or w_fp.get("decimalValue")
                            if w_val:
                                f_pricing = Decimal(str(w_val))
                                used_evidence = "script:next_data"
                                w_mrp = w_pricing.get("mrp", {})
                                w_mval = w_mrp.get("value") if isinstance(w_mrp, dict) else w_mrp
                                if w_mval:
                                    f_mrp = Decimal(str(w_mval))
                                break
            except Exception:
                pass

        # 2. window.__INITIAL_STATE__
        if not f_pricing:
            idx = html.find("window.__INITIAL_STATE__ = ")
            if idx != -1:
                try:
                    sub = html[idx + len("window.__INITIAL_STATE__ = "):]
                    f_state, _ = decoder.raw_decode(sub)
                    for k, v in f_state.items():
                        if isinstance(v, dict) and "price" in v:
                            p_val = v["price"].get("finalPrice", {}).get("value")
                            m_val = v["price"].get("mrp", {}).get("value")
                            if p_val:
                                f_pricing = Decimal(str(p_val))
                                used_evidence = "script:initial_state"
                            if m_val:
                                f_mrp = Decimal(str(m_val))
                            break
                except Exception:
                    pass

        # Shopsy & Flipkart state overrides:
        # Shopsy JSON-LD lists MRP under offers.price.
        # If true selling price f_pricing is found, it takes precedence.
        if f_pricing is not None:
            price = f_pricing
            currency = "INR"
            price_evidence = used_evidence or "script:next_data"
        if f_mrp is not None:
            mrp = f_mrp
            mrp_evidence = used_evidence or "script:next_data"
        if f_disc is not None and discount_pct is None:
            discount_pct = f_disc
        if f_img and not image:
            if f_img.startswith("http://"):
                f_img = "https://" + f_img[7:]
            elif f_img.startswith("//"):
                f_img = "https:" + f_img
            image = f_img

    # Calculate discount % if mrp and price both present
    if mrp is not None and price is not None and mrp > price and discount_pct is None:
        discount_pct = round(((mrp - price) / mrp) * Decimal(100), 1)

    # Determine availability independently
    availability, stock_evidence = _determine_stock_availability(soup, html, offers if isinstance(offers, dict) else {}, price)

    if mrp is not None:
        specs["mrp"] = str(mrp)
    if discount_pct is not None:
        specs["discount_percent"] = str(discount_pct)

    return {
        "title": title,
        "brand": brand,
        "model": model,
        "image_url": image,
        "identifiers": identifiers,
        "specs": specs,
        "price": price,
        "mrp": mrp,
        "discount_percent": discount_pct,
        "currency": currency,
        "availability": availability,
        "price_type": "selling" if price is not None else "unknown",
        "evidence": {
            "source": price_evidence if price is not None else ("json-ld" if product else "page-metadata"),
            "url": url,
            "mrp_evidence": mrp_evidence,
            "stock_evidence": stock_evidence,
            "mrp": str(mrp) if mrp is not None else None,
            "discount_percent": str(discount_pct) if discount_pct is not None else None,
        }
    }


@dataclass(frozen=True)
class PlatformAdapter:
    platform: Platform
    version: str = "2"

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
