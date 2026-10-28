import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import discovery, worker
from app.db import Base
from app.models import DiscoveryCandidate, DiscoveryRun, Listing, Observation, PlatformDiscovery, Product


class FakeResponse:
    def __init__(self, status_code=200, content_type="text/html", body=b"fixture", elapsed_ms=3):
        self.status_code = status_code
        self.content_type = content_type
        self.body = body
        self.elapsed_ms = elapsed_ms

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")


def complete_search(urls=()):
    return {"attempts": [{"status": "results_found", "request_attempted": True,
                          "http_status": 200, "content_type": "text/html", "candidate_urls_extracted": len(urls)}],
            "urls": list(urls), "complete": True, "reason": None}


def complete_sitemap(urls=()):
    return list(urls), True, "", {"status": "complete", "pages_checked": 1,
                                    "product_urls_extracted": len(urls), "limit_reached": False,
                                    "requests": [], "errors": [], "elapsed_ms": 3}


def product_data(url, **changes):
    data = {"title": "Brand Headphones Model X", "brand": "Brand", "model": "Model-X",
            "identifiers": {"gtin": "1234567890123"}, "specs": {"ram": "16GB"},
            "image_url": None, "price": 1200, "currency": "INR", "price_type": "selling",
            "availability": "in_stock", "evidence": {"source": "json-ld", "url": url}}
    data.update(changes)
    return data


def test_search_queries_use_model_variant_and_exclude_other_retailer_sku():
    product = {"title": "Apple iPhone 17 (White, 256 GB)", "brand": "APPLE", "model": None,
               "identifiers": {"sku": "MOBHQV9YAZYYWY8A"}, "specs": {}, "origin_platform": "flipkart"}
    queries = discovery.build_search_queries(product, "shopsy")
    assert queries[0]["query"] == "APPLE iPhone 17 256GB White"
    assert "MOBHQV9YAZYYWY8A" not in " ".join(query["query"] for query in queries)
    assert "256 GB" in queries[1]["query"]
    same_retailer = discovery.build_search_queries(product, "flipkart")
    assert "MOBHQV9YAZYYWY8A" in same_retailer[0]["query"]


def test_search_candidate_extractor_rejects_navigation_and_unwraps_product_link():
    html = '''<a href="/your-product-safety-alerts">Alerts</a>
      <a href="/s?k=iphone">Search</a>
      <a href="/Apple-iPhone-17/dp/B000000001">Phone</a>'''
    result = discovery.extract_candidate_urls(html, "https://www.amazon.in/s?k=iphone", "amazon_india")
    assert result["urls"] == ["https://www.amazon.in/dp/B000000001"]
    assert result["counts"]["rejected_non_product"] == 2


def test_croma_redirect_wrapper_is_unwrapped_to_a_product_page():
    html = '<a href="/l/redirect?url=https%3A%2F%2Fwww.croma.com%2Fapple-iphone%2Fp%2F324533">Phone</a>'
    result = discovery.extract_candidate_urls(html, "https://www.croma.com/category", "croma")
    assert result["urls"] == ["https://www.croma.com/apple-iphone/p/324533"]
    assert result["counts"]["redirect_wrappers_unwrapped"] == 1


def test_sitemap_reader_uses_declared_permitted_product_urls(monkeypatch):
    monkeypatch.setattr(discovery, "permitted_sitemaps", lambda adapter, **kwargs: ["https://www.croma.com/sitemap.xml"])
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    body = b'<urlset><url><loc>https://www.croma.com/brand/model/p/123</loc></url><url><loc>https://www.croma.com/login</loc></url></urlset>'
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: FakeResponse(content_type="application/xml", body=body))
    urls, complete, note, diagnostics = discovery.sitemap_product_urls(discovery.ADAPTERS["croma"])
    assert urls == ["https://www.croma.com/brand/model/p/123"]
    assert complete is True and not note
    assert diagnostics["pages_checked"] == 1


def test_sitemap_limit_is_incomplete(monkeypatch):
    monkeypatch.setattr(discovery, "permitted_sitemaps", lambda adapter, **kwargs: ["https://www.croma.com/sitemap.xml"])
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    body = b'<sitemapindex><sitemap><loc>https://www.croma.com/products-1.xml</loc></sitemap><sitemap><loc>https://www.croma.com/products-2.xml</loc></sitemap></sitemapindex>'
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: FakeResponse(content_type="application/xml", body=body))
    monkeypatch.setattr(discovery.settings, "max_sitemap_files", 1)
    urls, complete, note, diagnostics = discovery.sitemap_product_urls(discovery.ADAPTERS["croma"])
    assert urls == [] and not complete
    assert diagnostics["limit_reached"] is True
    assert "file limit" in note


def test_candidate_discovery_keeps_exact_and_similar_and_records_price_evidence(monkeypatch):
    exact_url = "https://www.croma.com/brand/model/p/123"
    similar_url = "https://www.croma.com/brand/other-model/p/456"
    monkeypatch.setattr(discovery, "sitemap_product_urls", lambda adapter, deadline=None: complete_sitemap([exact_url, similar_url]))
    monkeypatch.setattr(discovery, "search_product_urls", lambda adapter, product, deadline=None: complete_search())
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: FakeResponse())
    def extract(self, html, url):
        return product_data(url, specs={"ram": "16GB"} if url == exact_url else {})
    monkeypatch.setattr(discovery.PlatformAdapter, "extract", extract)
    source = {"title": "Brand Headphones Model X", "brand": "Brand", "model": "Model-X",
              "identifiers": {"gtin": "1234567890123"}, "specs": {"ram": "16GB"},
              "origin_url": "https://www.amazon.in/dp/B000000001", "origin_platform": "amazon_india"}
    result = discovery.discover_platform_candidates("croma", source, [])
    assert result["status"] == "exact_match_found"
    assert {item["match"]["classification"] for item in result["candidates"]} == {"exact", "probable"}
    assert result["diagnostics"]["candidates"]["pages_checked"] == 2
    assert result["diagnostics"]["candidates"]["exact_prices_verified"] == 1
    assert result["diagnostics"]["candidates"]["selling_prices_verified"] == 2


def test_exact_page_without_verified_price_is_price_unavailable(monkeypatch):
    url = "https://www.croma.com/brand/model/p/123"
    monkeypatch.setattr(discovery, "sitemap_product_urls", lambda adapter, deadline=None: complete_sitemap([url]))
    monkeypatch.setattr(discovery, "search_product_urls", lambda adapter, product, deadline=None: complete_search())
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr(discovery.PlatformAdapter, "extract", lambda self, html, url: product_data(
        url, price=999, currency="INR", price_type="unknown", evidence={"source": "page-metadata", "url": url}))
    source = {"title": "Brand Headphones Model X", "model": "Model-X", "identifiers": {"gtin": "1234567890123"},
              "specs": {"ram": "16GB"}, "origin_url": "https://www.amazon.in/dp/B000000001"}
    result = discovery.discover_platform_candidates("croma", source, [])
    assert result["status"] == "price_unavailable"
    assert result["candidates"][0]["price"] is None
    assert result["diagnostics"]["candidates"]["details"][0]["price_status"] == "unavailable_or_unverified"


def test_incomplete_sitemap_and_empty_search_do_not_become_no_match(monkeypatch):
    sitemap = {"status": "incomplete", "pages_checked": 3, "product_urls_extracted": 0,
               "limit_reached": True, "requests": [], "errors": [], "elapsed_ms": 9}
    monkeypatch.setattr(discovery, "sitemap_product_urls", lambda adapter, deadline=None: ([], False, "file limit", sitemap))
    monkeypatch.setattr(discovery, "search_product_urls", lambda adapter, product, deadline=None: {
        "attempts": [{"status": "no_product_urls", "request_attempted": True, "http_status": 200,
                      "content_type": "text/html", "candidate_urls_extracted": 0}],
        "urls": [], "complete": False, "reason": "No product links parsed."})
    result = discovery.discover_platform_candidates("croma", {"title": "Brand Model X", "origin_url": "https://www.amazon.in/dp/B000000001"}, [])
    assert result["status"] == "could_not_check"
    assert result["diagnostics"]["outcome"] == "discovery_incomplete"


def test_search_404_is_recorded_and_not_counted_as_success(monkeypatch):
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: FakeResponse(404, "text/html", b"not found"))
    product = {"title": "Apple iPhone 17 White 256GB", "brand": "Apple", "origin_platform": "flipkart", "identifiers": {}, "specs": {}}
    result = discovery._search_attempt(discovery.ADAPTERS["ajio"], discovery.build_search_queries(product, "ajio")[0])
    assert result["status"] == "http_error"
    assert result["http_status"] == 404
    assert result["request_attempted"] is True
    assert result["candidate_urls_extracted"] == 0


def test_search_result_fallback_only_runs_after_parsed_empty_primary(monkeypatch):
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    responses = [FakeResponse(body=b'<html><a href="/search?q=empty">search</a></html>'),
                 FakeResponse(body=b'<html><a href="/apple-iphone-17/p/itm12345">product</a></html>')]
    monkeypatch.setattr(discovery, "fetch_bounded_response", lambda *args, **kwargs: responses.pop(0))
    product = {"title": "Apple iPhone 17 White 256 GB", "brand": "Apple", "origin_platform": "flipkart", "identifiers": {}, "specs": {}}
    result = discovery.search_product_urls(discovery.ADAPTERS["shopsy"], product)
    assert len(result["attempts"]) == 2
    assert result["urls"] == ["https://www.shopsy.in/apple-iphone-17/p/itm12345"]
    assert result["complete"] is True


def test_worker_persists_diagnostics_and_verified_offer(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", Session)
    with Session() as db:
        product = Product(title="Widget X", model="W-X", identifiers={"gtin": "1234567890123"}, specs={}, origin_url="https://www.amazon.in/dp/B000000001", origin_platform="amazon_india")
        db.add(product); db.flush()
        run = DiscoveryRun(product_id=product.id, status="searching")
        db.add(run); db.flush()
        check = PlatformDiscovery(run_id=run.id, platform="croma", status="searching")
        db.add(check); db.commit()
        run_id, check_id = run.id, check.id
    candidate = {"url": "https://www.croma.com/brand/widget/p/123", "title": "Widget X", "brand": "Brand", "model": "W-X", "identifiers": {"gtin": "1234567890123"}, "specs": {}, "image_url": None, "match": {"classification": "exact", "evidence": ["gtin matches"], "missing": [], "conflicts": []}, "price": 900, "currency": "INR", "price_type": "selling", "availability": "in_stock", "evidence": {"source": "json-ld"}}
    diagnostics = {"outcome": "exact_product_price_verified", "search": {"attempts": []}}
    monkeypatch.setattr(worker, "discover_platform_candidates", lambda *args: {"status": "exact_match_found", "message": None, "candidates": [candidate], "diagnostics": diagnostics})
    worker.process_discovery_runs()
    with Session() as db:
        check = db.get(PlatformDiscovery, check_id)
        run = db.get(DiscoveryRun, run_id)
        assert check.status == "exact_match_found" and run.status == "completed"
        assert check.diagnostics["outcome"] == "exact_product_price_verified"
        assert db.scalar(select(DiscoveryCandidate).where(DiscoveryCandidate.check_id == check_id)).price == 900
        assert db.scalar(select(Listing).where(Listing.product_id == run.product_id, Listing.platform == "croma")) is not None
        assert db.scalar(select(Observation).join(Listing).where(Listing.product_id == run.product_id, Listing.platform == "croma")).price == 900
    engine.dispose()


def test_platform_failure_retries_once_then_stays_could_not_check(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", Session)
    with Session() as db:
        product = Product(title="Widget Y", identifiers={}, specs={})
        db.add(product); db.flush()
        run = DiscoveryRun(product_id=product.id, status="searching")
        db.add(run); db.flush()
        check = PlatformDiscovery(run_id=run.id, platform="croma", status="searching")
        db.add(check); db.commit()
        check_id = check.id
    monkeypatch.setattr(worker, "discover_platform_candidates", lambda *args: (_ for _ in ()).throw(TimeoutError("retailer timed out")))
    worker.process_discovery_runs()
    with Session() as db:
        assert db.get(PlatformDiscovery, check_id).status == "searching"
    worker.process_discovery_runs()
    with Session() as db:
        assert db.get(PlatformDiscovery, check_id).status == "could_not_check"
    engine.dispose()


def test_partial_refresh_keeps_last_verified_price_visible():
    from app.service import compare_saved_product
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        product = Product(title="Widget X", identifiers={}, specs={}, origin_url="https://www.amazon.in/dp/B000000001", origin_platform="amazon_india")
        db.add(product); db.flush()
        listing = Listing(product_id=product.id, platform="amazon_india", url=product.origin_url, title=product.title,
                          brand=None, model=None, identifiers={}, specs={}, image_url=None)
        db.add(listing); db.flush()
        db.add(Observation(listing_id=listing.id, price=900, currency="INR", price_type="selling", availability="in_stock", status="success"))
        db.add(Observation(listing_id=listing.id, price=None, currency=None, price_type="unknown", availability="unknown", status="partial"))
        db.commit()
        result = compare_saved_product(product.id, db)
        assert result["offers"][0]["price"] == 900
        assert result["offers"][0]["status"] == "success"
    engine.dispose()

def test_incomplete_diagnostic_retries_even_if_result_status_is_misreported(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(worker, "SessionLocal", Session)
    with Session() as db:
        product = Product(title="Widget Z", identifiers={}, specs={})
        db.add(product); db.flush()
        run = DiscoveryRun(product_id=product.id, status="searching")
        db.add(run); db.flush()
        check = PlatformDiscovery(run_id=run.id, platform="croma", status="searching")
        db.add(check); db.commit()
        check_id = check.id
    monkeypatch.setattr(worker, "discover_platform_candidates", lambda *args: {
        "status": "no_match_found", "message": "sitemap limit reached", "candidates": [],
        "diagnostics": {"outcome": "discovery_incomplete", "complete": False}})
    worker.process_discovery_runs()
    with Session() as db:
        assert db.get(PlatformDiscovery, check_id).status == "searching"
    worker.process_discovery_runs()
    with Session() as db:
        assert db.get(PlatformDiscovery, check_id).status == "could_not_check"
    engine.dispose()


def test_amazon_result_urls_collapse_asins_and_keep_title_labels():
    html = """<h2><a href='/Apple-iPhone-17-Pro-Max/dp/B000000001/ref=sr_1_1'>Apple iPhone 17 Pro Max 256GB</a></h2>
      <h2><a href='/Apple-iPhone-17-White/dp/B000000002/ref=sr_1_2'>Apple iPhone 17 White 256GB</a></h2>
      <a href='/other/dp/B000000001/ref=sr_1_3'>duplicate ad</a>"""
    result = discovery.extract_candidate_urls(html, "https://www.amazon.in/s?k=iphone", "amazon_india")
    assert result["urls"] == ["https://www.amazon.in/dp/B000000001", "https://www.amazon.in/dp/B000000002"]
    assert result["titles"]["https://www.amazon.in/dp/B000000002"] == "Apple iPhone 17 White 256GB"
    assert result["counts"]["duplicates"] == 1


def test_candidate_ranking_penalizes_explicit_model_variant_conflicts():
    source = {"title": "Apple iPhone 17 (White, 256 GB)", "brand": "Apple", "specs": {}}
    plain = discovery._candidate_score("https://www.amazon.in/Apple-iPhone-17/dp/B000000002", source, "amazon_india", "Apple iPhone 17 White 256GB")
    pro_max = discovery._candidate_score("https://www.amazon.in/Apple-iPhone-17-Pro-Max/dp/B000000001", source, "amazon_india", "Apple iPhone 17 Pro Max 256GB")
    assert plain > pro_max


def test_candidate_page_fetches_use_bounded_concurrency(monkeypatch):
    import threading
    import time

    urls = [f"https://www.croma.com/brand/model/p/{index}" for index in range(4)]
    monkeypatch.setattr(discovery, "sitemap_product_urls", lambda adapter, deadline=None: complete_sitemap(urls))
    monkeypatch.setattr(discovery, "search_product_urls", lambda adapter, product, deadline=None: complete_search())
    monkeypatch.setattr(discovery, "validate_permitted_page", lambda url, **kwargs: url)
    monkeypatch.setattr(discovery.settings, "discovery_candidate_concurrency", 2)
    lock = threading.Lock()
    active = 0
    peak = 0

    def fetch(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.04)
        with lock:
            active -= 1
        return FakeResponse()

    monkeypatch.setattr(discovery, "fetch_bounded_response", fetch)
    monkeypatch.setattr(discovery.PlatformAdapter, "extract", lambda self, html, url: product_data(url))
    source = {"title": "Brand Headphones Model X", "brand": "Brand", "model": "Model-X",
              "identifiers": {"gtin": "1234567890123"}, "specs": {"ram": "16GB"},
              "origin_url": "https://www.amazon.in/dp/B000000001", "origin_platform": "amazon_india"}

    result = discovery.discover_platform_candidates("croma", source, [])

    assert peak == 2
    assert result["diagnostics"]["candidates"]["pages_checked"] == 4


def test_expired_overall_deadline_returns_incomplete_without_retailer_requests(monkeypatch):
    import time

    def unexpected_request(*args, **kwargs):
        raise AssertionError("no retailer request should start after the deadline")

    monkeypatch.setattr(discovery, "permitted_sitemaps", unexpected_request)
    monkeypatch.setattr(discovery, "validate_permitted_page", unexpected_request)
    monkeypatch.setattr(discovery, "fetch_bounded_response", unexpected_request)
    source = {"title": "Apple iPhone 17 White 256 GB", "brand": "Apple", "origin_url": "https://www.flipkart.com/apple-iphone/p/item"}

    result = discovery.discover_platform_candidates("amazon_india", source, [], time.monotonic() - 1)

    assert result["status"] == "could_not_check"
    assert result["diagnostics"]["deadline_reached"] is True
    assert result["diagnostics"]["complete"] is False
