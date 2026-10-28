import json
from decimal import Decimal
import pytest
from app.adapters.registry import extract_product, PLATFORMS, ADAPTERS
from app.matching import match_product
from app import discovery


def test_flipkart_and_shopsy_price_selectors():
    html_fk = '''
    <html>
      <head><title>Apple iPhone 15 (Blue, 128 GB)</title></head>
      <body>
        <h1>Apple iPhone 15 (Blue, 128 GB)</h1>
        <div class="Nx9bqj CxhGGd">&#8377;69,999</div>
      </body>
    </html>
    '''
    data = extract_product(html_fk, "https://www.flipkart.com/apple-iphone-15/p/itm123")
    assert data["title"] == "Apple iPhone 15 (Blue, 128 GB)"
    assert data["price"] == Decimal("69999.00")
    assert data["currency"] == "INR"


def test_croma_price_selector():
    html_croma = '''
    <html>
      <head><title>Apple iPhone 15 (128GB, Black) - Croma</title></head>
      <body>
        <h1>Apple iPhone 15 (128GB, Black)</h1>
        <span class="amount">&#8377;71,490.00</span>
      </body>
    </html>
    '''
    data = extract_product(html_croma, "https://www.croma.com/apple-iphone-15/p/123")
    assert data["price"] == Decimal("71490.00")
    assert data["currency"] == "INR"


def test_ajio_price_selector():
    html_ajio = '''
    <html>
      <head><title>Apple iPhone 15 (128GB, Blue)</title></head>
      <body>
        <span class="prod-sp">&#8377;72,999</span>
      </body>
    </html>
    '''
    data = extract_product(html_ajio, "https://www.ajio.com/apple-iphone-15/p/49123")
    assert data["price"] == Decimal("72999.00")
    assert data["currency"] == "INR"


def test_brand_extraction_avoids_retailer_name_in_jsonld():
    html_shopsy = '''
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Apple iPhone 15 (Blue, 128 GB)",
          "brand": {"@type": "Brand", "name": "Shopsy"},
          "offers": {
            "@type": "Offer",
            "price": "74900.00",
            "priceCurrency": "INR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body></body>
    </html>
    '''
    data = extract_product(html_shopsy, "https://www.shopsy.in/apple-iphone-15/p/itm123")
    assert data["brand"] == "Apple"
    assert data["price"] == Decimal("74900.00")
    assert data["availability"] == "in_stock"


def test_shopsy_and_flipkart_cross_platform_matching():
    anchor = {
        "title": "Apple iPhone 15 (Blue, 128 GB)",
        "brand": "APPLE",
        "model": "iPhone 15",
        "identifiers": {"sku": "MOBHQV9YZGYG64U7"},
        "specs": {"storage": "128 GB", "color": "Blue"}
    }
    candidate_shopsy = {
        "title": "Apple iPhone 15 (Blue, 128 GB)",
        "brand": "Shopsy",
        "model": None,
        "identifiers": {"sku": "MOBHQV9YZGYG64U7"},
        "specs": {}
    }
    match = match_product(anchor, candidate_shopsy)
    assert match["classification"] == "exact"
    assert not match["conflicts"]


def test_cross_platform_discovery_exact_match_found(monkeypatch):
    source = {
        "title": "Apple iPhone 15 (Blue, 128 GB)",
        "brand": "Apple",
        "model": "iPhone 15",
        "identifiers": {},
        "specs": {"storage": "128 GB", "color": "Blue"},
        "origin_url": "https://www.flipkart.com/apple-iphone-15/p/itm123",
        "origin_platform": "flipkart"
    }

    class FakeResponse:
        def __init__(self, body, status_code=200):
            self.body = body.encode("utf-8") if isinstance(body, str) else body
            self.status_code = status_code
            self.content_type = "text/html"
            self.elapsed_ms = 10
        @property
        def text(self):
            return self.body.decode("utf-8")

    search_html = '''
    <html>
      <body>
        <a href="/apple-iphone-15-blue-128-gb/p/itm387c20f1f5347">Apple iPhone 15 (Blue, 128 GB)</a>
        <a href="/apple-iphone-15-plus-blue-128-gb/p/itm999">Apple iPhone 15 Plus (Blue, 128 GB)</a>
      </body>
    </html>
    '''
    product_html = '''
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Apple iPhone 15 (Blue, 128 GB)",
          "brand": "Apple",
          "offers": {
            "@type": "Offer",
            "price": "74900.00",
            "priceCurrency": "INR",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
      </head>
      <body></body>
    </html>
    '''

    def fake_fetch(url, *args, **kwargs):
        if "/search" in url:
            return FakeResponse(search_html)
        else:
            return FakeResponse(product_html)

    monkeypatch.setattr(discovery, "fetch_bounded_response", fake_fetch)
    monkeypatch.setattr(discovery, "validate_public_product_url", lambda url: url)

    result = discovery.discover_platform_candidates("shopsy", source, [])
    assert result["status"] == "exact_match_found"
    assert result["diagnostics"]["outcome"] == "exact_product_price_verified"
    assert len(result["candidates"]) >= 1
    exact_cand = next(c for c in result["candidates"] if c["match"]["classification"] == "exact")
    assert exact_cand["price"] == Decimal("74900.00")
    assert exact_cand["currency"] == "INR"
