import json
import pytest
from app.adapters import ADAPTERS, PLATFORMS, adapter_for_url


@pytest.mark.parametrize("key,domain", [("amazon_india", "amazon.in"), ("flipkart", "flipkart.com"), ("shopsy", "shopsy.in"), ("myntra", "myntra.com"), ("meesho", "meesho.com"), ("ajio", "ajio.com"), ("croma", "croma.com")])
def test_platform_router(key, domain):
    assert adapter_for_url(f"https://www.{domain}/product/example") is ADAPTERS[key]


def test_shopsy_does_not_route_as_flipkart():
    assert adapter_for_url("https://www.shopsy.in/p/example") is ADAPTERS["shopsy"]
    assert ADAPTERS["shopsy"] is not ADAPTERS["flipkart"]


def test_extracts_structured_price_stock_and_variant():
    from app.adapters.registry import extract_product
    page = '<script type="application/ld+json">' + json.dumps({"@type": "Product", "name": "Camera X", "brand": {"@type": "Brand", "name": "Brand"}, "sku": "X-1", "offers": {"@type": "Offer", "price": "999.5", "priceCurrency": "INR", "availability": "https://schema.org/InStock"}}) + "</script>"
    data = extract_product(page, "https://www.croma.com/p/x")
    assert data["title"] == "Camera X"
    assert data["price"] == 999.50
    assert data["currency"] == "INR"
    assert data["availability"] == "in_stock"
    assert data["identifiers"]["sku"] == "X-1"


def test_missing_price_does_not_invent_price():
    from app.adapters.registry import extract_product
    data = extract_product('<meta property="og:title" content="Sample item">', "https://www.amazon.in/dp/x")
    assert data["price"] is None
    assert data["availability"] == "unknown"


def test_amazon_current_price_selector_is_used_without_mrp():
    from app.adapters.registry import extract_product
    page = '<meta property="og:title" content="Laptop X">' \
           '<div id="corePriceDisplay_desktop_feature_div"><span class="a-price"><span class="a-offscreen">₹54,999</span></span></div>'
    data = extract_product(page, "https://www.amazon.in/dp/x")
    assert data["price"] == 54999
    assert data["currency"] == "INR"
    assert data["price_type"] == "selling"


def test_amazon_price_to_pay_beats_blank_offscreen_and_ignores_mrp():
    from app.adapters.registry import extract_product
    page = '''<meta property="og:title" content="Lenovo IdeaPad Slim 3">
      <div id="corePriceDisplay_desktop_feature_div">
        <span class="a-price priceToPay"><span class="a-offscreen"></span><span class="a-price-whole">73,799</span></span>
        <span class="a-price a-text-price"><span class="a-offscreen">82,690</span></span>
      </div>'''
    data = extract_product(page, "https://www.amazon.in/dp/B0GDQFZBQC")
    assert data["price"] == 73799
    assert data["currency"] == "INR"


def test_price_selector_ignores_mrp_only_markup():
    from app.adapters.registry import extract_product
    page = '<meta property="og:title" content="Laptop X"><span class="a-text-price">₹64,999</span>'
    data = extract_product(page, "https://www.amazon.in/dp/x")
    assert data["price"] is None


def test_discovery_is_never_claimed_supported_by_default():
    assert len(PLATFORMS) == 7
    assert all(p.discovery_status != "supported" for p in PLATFORMS)


def test_extracts_full_schema_product_type_and_keeps_model_distinct_from_sku():
    from app.adapters.registry import extract_product
    page = '<script type="application/ld+json">' + json.dumps({
        "@type": "https://schema.org/Product", "name": "Phone X", "model": "PX-10",
        "sku": "STORE-55", "offers": {"@type": "Offer", "price": "100", "priceCurrency": "INR"}
    }) + "</script>"
    data = extract_product(page, "https://www.croma.com/p/phone-x")
    assert data["title"] == "Phone X"
    assert data["model"] == "PX-10"
    assert data["identifiers"] == {"sku": "STORE-55"}


def test_multiple_schema_offers_with_different_prices_are_not_arbitrarily_verified():
    from app.adapters.registry import extract_product
    page = '<script type="application/ld+json">' + json.dumps({
        "@type": "Product", "name": "Phone X",
        "offers": [
            {"@type": "Offer", "price": "89999", "priceCurrency": "INR"},
            {"@type": "Offer", "price": "99900", "priceCurrency": "INR"},
        ]
    }) + "</script>"
    data = extract_product(page, "https://www.croma.com/phone-x/p/123")
    assert data["price"] is None
    assert data["price_type"] == "unknown"


def test_shopsy_next_data_price_and_image_extracted_correctly():
    from app.adapters.registry import extract_product
    next_payload = {
        "props": {
            "pageProps": {
                "initialState": {
                    "pageData": {
                        "RESPONSE": {
                            "pageData": {
                                "pageContext": {
                                    "pricing": {
                                        "finalPrice": {"value": 91999, "currency": "INR"},
                                        "mrp": 99900,
                                        "totalDiscount": 7
                                    },
                                    "imageUrl": "http://rukmini1.flixcart.com/image/{@width}/{@height}/test.jpeg"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    page = f'''<meta property="og:title" content="Apple iPhone 17 (Black, 256 GB)">
    <script type="application/ld+json">{json.dumps({"@type": "Product", "name": "Apple iPhone 17", "offers": {"@type": "Offer", "price": "99900", "priceCurrency": "INR", "availability": "https://schema.org/InStock"}})}</script>
    <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_payload)}</script>'''
    data = extract_product(page, "https://www.shopsy.in/apple-iphone-17-black-256-gb/p/itmc61b40459dd98")
    assert data["price"] == 91999
    assert data["mrp"] == 99900
    assert data["discount_percent"] == 7
    assert data["evidence"]["source"] == "script:next_data"
    assert data["image_url"] == "https://rukmini1.flixcart.com/image/800/800/test.jpeg"
