from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import AlertEvent, DiscoveryCandidate, DiscoveryRun, Listing, Observation, PlatformDiscovery, Product, TrackingJob
from app.service import compare_saved_product, inspect_url


def make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_inspect_persists_source_observation_and_comparison(monkeypatch):
    from app import service
    monkeypatch.setattr(service, "validate_permitted_page", lambda url: url)
    monkeypatch.setattr(service, "fetch_bounded_text", lambda *args, **kwargs: '<script type="application/ld+json">{"@type":"Product","name":"Widget Z","sku":"WZ-1","offers":{"@type":"Offer","price":"1500","priceCurrency":"INR","availability":"https://schema.org/InStock"}}</script>')
    engine, Session = make_db()
    with Session() as db:
        result = inspect_url("https://www.amazon.in/dp/example", db)
        assert result["product"]["title"] == "Widget Z"
        assert result["discovery_run_id"]
        checks = list(db.scalars(select(PlatformDiscovery).where(PlatformDiscovery.run_id == result["discovery_run_id"])))
        assert len(checks) == 7
        source_check = next(check for check in checks if check.platform == "amazon_india")
        assert source_check.status == "source_checked"
        assert "cross-listing discovery is skipped" in source_check.message
        saved = compare_saved_product(result["product"]["id"], db)
        assert saved["offers"][0]["price"] == 1500
        assert saved["lowest_verified_offer"]["url"] == "https://www.amazon.in/dp/example"
        assert len(list(db.scalars(select(Observation)))) == 1
        assert len(list(db.scalars(select(Listing)))) == 1
    engine.dispose()


def test_discovery_status_and_manual_candidate_fallback(monkeypatch):
    from app import main
    engine, Session = make_db()
    with Session() as db:
        product = Product(title="Camera Q", identifiers={}, specs={}, origin_url="https://www.amazon.in/dp/camera", origin_platform="amazon_india")
        db.add(product)
        db.flush()
        run = DiscoveryRun(product_id=product.id, status="completed")
        db.add(run)
        db.flush()
        source = PlatformDiscovery(run_id=run.id, platform="amazon_india", status="exact_match_found")
        croma = PlatformDiscovery(run_id=run.id, platform="croma", status="exact_match_found")
        similar = PlatformDiscovery(run_id=run.id, platform="myntra", status="similar_product_found")
        db.add_all([source, croma, similar])
        db.flush()
        db.add(DiscoveryCandidate(check_id=source.id, url="https://www.amazon.in/dp/camera", title="Camera Q", identifiers={"gtin":"1234567890123"}, specs={}, match_classification="exact", match_evidence={"evidence": []}, price=1400, currency="INR", price_type="selling", availability="unknown"))
        db.add(DiscoveryCandidate(check_id=croma.id, url="https://www.croma.com/p/camera-q", title="Camera Q", identifiers={"gtin":"1234567890123"}, specs={}, match_classification="exact", match_evidence={"evidence": ["gtin matches"]}, price=700, currency="INR", price_type="selling", availability="in_stock"))
        db.add(DiscoveryCandidate(check_id=similar.id, url="https://www.myntra.com/p/camera-q", title="Camera Q alternate", identifiers={}, specs={}, match_classification="probable", match_evidence={"evidence": [], "missing": ["variant"]}, price=100, currency="INR", price_type="selling", availability="in_stock"))
        db.add(croma)
        db.commit()
        run_id, croma_id = run.id, croma.id
    def override_db():
        with Session() as db:
            yield db
    monkeypatch.setattr(main, "validate_public_product_url", lambda url: url)
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        status = client.get(f"/api/discovery/{run_id}")
        assert status.status_code == 200
        assert next(c for c in status.json()["checks"] if c["platform"] == "croma")["status"] == "exact_match_found"
        assert status.json()["lowest_verified_offer"]["platform"] == "croma"
        assert status.json()["lowest_verified_offer"]["price"] == 700
        assert status.json()["checks"][2]["candidates"][0]["match_classification"] == "probable"
        added = client.post(f"/api/discovery/{run_id}/candidates", json={"url": "https://www.croma.com/p/camera-q"})
        assert added.status_code == 200
        assert added.json()["status"] == "searching"
        with Session() as db:
            check = db.get(PlatformDiscovery, croma_id)
            assert check.manual_urls == ["https://www.croma.com/p/camera-q"]
            assert db.get(DiscoveryRun, run_id).status == "searching"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_inspect_worker_discovery_and_exact_price_api_flow(monkeypatch):
    from app import main, service, worker
    product_html = '<script type="application/ld+json">{"@type":"Product","name":"Widget Z","brand":"Brand","gtin13":"1234567890123","offers":{"@type":"Offer","price":"1200","priceCurrency":"INR","availability":"https://schema.org/InStock"}}</script>'
    monkeypatch.setattr(service, "validate_permitted_page", lambda url: url)
    monkeypatch.setattr(service, "fetch_bounded_text", lambda *args, **kwargs: product_html)
    monkeypatch.setattr(main, "inspect_url", service.inspect_url)
    candidate = {"url": "https://www.flipkart.com/widget-z/p/item", "title": "Widget Z", "brand": "Brand", "model": None,
                 "identifiers": {"gtin": "1234567890123"}, "specs": {}, "image_url": None,
                 "match": {"classification": "exact", "evidence": ["exact gtin"], "missing": [], "conflicts": []},
                 "price": 800, "currency": "INR", "price_type": "selling", "availability": "in_stock"}
    monkeypatch.setattr(worker, "discover_platform_candidates", lambda *args: {"status": "exact_match_found", "message": None, "candidates": [candidate]})
    engine, Session = make_db()
    monkeypatch.setattr(worker, "SessionLocal", Session)
    def override_db():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        inspected = client.post("/api/products/inspect", json={"url": "https://www.amazon.in/dp/widget-z"})
        assert inspected.status_code == 200
        run_id = inspected.json()["discovery_run_id"]
        worker.process_discovery_runs()
        run = client.get(f"/api/discovery/{run_id}").json()
        flipkart = next(c for c in run["checks"] if c["platform"] == "flipkart")
        assert flipkart["status"] == "exact_match_found"
        assert run["lowest_verified_offer"]["platform"] == "flipkart"
        product_id = inspected.json()["product"]["id"]
        comparison = client.get(f"/api/products/{product_id}").json()
        assert comparison["lowest_verified_offer"]["platform"] == "flipkart"
        assert comparison["lowest_verified_offer"]["price"] == 800
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_tracking_and_history_api_uses_database():
    engine, Session = make_db()
    with Session() as db:
        product = Product(title="Fixture product", identifiers={}, specs={}, origin_url="https://www.croma.com/p/example", origin_platform="croma")
        db.add(product)
        db.flush()
        listing = Listing(product_id=product.id, platform="croma", url=product.origin_url, title=product.title, identifiers={}, specs={})
        db.add(listing)
        db.flush()
        db.add(Observation(listing_id=listing.id, price=500, currency="INR", price_type="selling", availability="unknown", status="success"))
        db.commit()
        product_id = product.id
    def override_db():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get(f"/api/products/{product_id}")
        assert response.status_code == 200
        assert response.json()["offers"][0]["price"] == 500.0
        tracking = client.post("/api/tracking", json={"product_id": product_id, "target_price": 450})
        assert tracking.status_code == 200
        tracking_id = tracking.json()["id"]
        assert client.patch(f"/api/tracking/{tracking_id}", json={"active": False}).json()["active"] is False
        assert len(client.get(f"/api/products/{product_id}/history").json()["observations"]) == 1
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_stale_observation_is_not_selected_as_lowest():
    engine, Session = make_db()
    with Session() as db:
        product = Product(title="Old item", model="M-1", identifiers={"gtin": "1234567890123"}, specs={}, origin_url="https://www.croma.com/p/old", origin_platform="croma")
        db.add(product)
        db.flush()
        listing = Listing(product_id=product.id, platform="croma", url=product.origin_url, title=product.title, model=product.model, identifiers=product.identifiers, specs={})
        db.add(listing)
        db.flush()
        db.add(Observation(listing_id=listing.id, price=300, currency="INR", price_type="selling", availability="unknown", status="success", observed_at=datetime.now(timezone.utc) - timedelta(hours=25)))
        db.commit()
        result = compare_saved_product(product.id, db)
        assert result["offers"][0]["freshness"] == "stale"
        assert result["lowest_verified_offer"] is None
    engine.dispose()


def test_alert_modes_are_validated_scoped_and_persisted():
    engine, Session = make_db()
    with Session() as db:
        product = Product(title="Phone X", model="PX-1", identifiers={"gtin": "1234567890123"}, specs={"ram": "8GB"},
                          origin_url="https://www.amazon.in/dp/phone", origin_platform="amazon_india")
        db.add(product)
        db.flush()
        source = Listing(product_id=product.id, platform="amazon_india", url=product.origin_url, title=product.title,
                         model=product.model, identifiers=product.identifiers, specs=product.specs)
        other_product = Product(title="Other", identifiers={}, specs={})
        db.add_all([source, other_product])
        db.flush()
        wrong_owner = Listing(product_id=other_product.id, platform="croma", url="https://www.croma.com/p/other", title="Other", identifiers={}, specs={})
        wrong_variant = Listing(product_id=product.id, platform="croma", url="https://www.croma.com/p/phone-4gb", title="Phone X", model="PX-1",
                                identifiers=product.identifiers, specs={"ram": "4GB"})
        db.add_all([wrong_owner, wrong_variant])
        db.commit()
        product_id, source_id = product.id, source.id
        wrong_owner_id, wrong_variant_id = wrong_owner.id, wrong_variant.id

    def override_db():
        with Session() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        any_drop = client.post("/api/tracking", json={"product_id": product_id, "mode": "any_drop"})
        assert any_drop.status_code == 200
        assert any_drop.json()["mode"] == "any_drop"
        assert any_drop.json()["listing_id"] is None
        target = client.post("/api/tracking", json={"product_id": product_id, "mode": "target_price", "target_price": "799.90", "listing_id": source_id})
        assert target.status_code == 200
        assert target.json()["mode"] == "target_price"
        assert Decimal(str(target.json()["target_price"])) == Decimal("799.90")
        repeated = client.post("/api/tracking", json={"product_id": product_id, "mode": "target_price", "target_price": "799.90", "listing_id": source_id})
        assert repeated.json()["id"] == target.json()["id"]
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "target_price", "target_price": "0"}).status_code == 422
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "target_price"}).status_code == 422
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "any_drop", "target_price": "10"}).status_code == 422
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "target_price", "target_price": "1.001"}).status_code == 422
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "any_drop", "listing_id": wrong_owner_id}).status_code == 422
        assert client.post("/api/tracking", json={"product_id": product_id, "mode": "any_drop", "listing_id": wrong_variant_id}).status_code == 422
        with Session() as db:
            jobs = list(db.scalars(select(TrackingJob).order_by(TrackingJob.id)))
            assert [(job.mode, job.listing_id) for job in jobs] == [("any_drop", None), ("target_price", source_id)]
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_price_drop_alert_persists_once_and_ignores_scrape_failure(monkeypatch):
    from app import worker
    from app.adapters import PlatformAdapter
    from app.models import AlertEvent, TrackingJob
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with Session() as db:
        product = Product(title="Watch X", identifiers={"gtin": "1234567890123"}, specs={},
                          origin_url="https://www.amazon.in/dp/watch", origin_platform="amazon_india")
        db.add(product)
        db.flush()
        listing = Listing(product_id=product.id, platform="amazon_india", url=product.origin_url,
                          title=product.title, identifiers=product.identifiers, specs={})
        db.add(listing)
        db.flush()
        db.add(Observation(listing_id=listing.id, price=100, currency="INR", price_type="selling",
                           availability="in_stock", status="success", observed_at=now - timedelta(hours=48)))
        job = TrackingJob(product_id=product.id, mode="any_drop", next_run_at=now - timedelta(minutes=1))
        db.add(job)
        db.commit()
        listing_id, job_id = listing.id, job.id
    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(worker, "validate_permitted_page", lambda url: url)
    monkeypatch.setattr(worker, "fetch_bounded_text", lambda *args, **kwargs: "fixture")
    prices = iter(["90", "90"])
    monkeypatch.setattr(PlatformAdapter, "extract", lambda self, html, url: {
        "price": Decimal(next(prices)), "currency": "INR", "price_type": "selling", "availability": "in_stock",
        "evidence": {}, "title": "Watch X", "brand": None, "model": None, "identifiers": {"gtin": "1234567890123"}, "specs": {}, "image_url": None
    })
    worker.check_due_jobs()
    with Session() as db:
        event = db.scalar(select(AlertEvent).where(AlertEvent.kind == "price_drop"))
        assert event is not None and event.listing_id == listing_id
        assert event.event_key
        db.get(TrackingJob, job_id).next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    worker.check_due_jobs()
    with Session() as db:
        assert len(list(db.scalars(select(AlertEvent).where(AlertEvent.kind == "price_drop")))) == 1
        db.get(TrackingJob, job_id).next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    monkeypatch.setattr(worker, "fetch_bounded_text", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("offline")))
    worker.check_due_jobs()
    with Session() as db:
        assert len(list(db.scalars(select(AlertEvent)))) == 1
    engine.dispose()


def test_variant_change_during_refresh_never_triggers_price_drop(monkeypatch):
    from app import worker
    from app.adapters import PlatformAdapter
    now = datetime.now(timezone.utc)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as db:
        product = Product(title="Phone X", model="PX-1", identifiers={"gtin": "1234567890123"},
                          specs={"ram": "8GB"}, origin_url="https://www.amazon.in/dp/phone", origin_platform="amazon_india")
        db.add(product)
        db.flush()
        listing = Listing(product_id=product.id, platform="croma", url="https://www.croma.com/p/phone",
                          title="Phone X", model="PX-1", identifiers={"gtin": "1234567890123"}, specs={"ram": "8GB"})
        db.add(listing)
        db.flush()
        db.add(Observation(listing_id=listing.id, price=1000, currency="INR", price_type="selling",
                           availability="in_stock", status="success", observed_at=now - timedelta(hours=1)))
        db.add(TrackingJob(product_id=product.id, listing_id=listing.id, mode="any_drop",
                           next_run_at=now - timedelta(minutes=1)))
        db.commit()
    monkeypatch.setattr(worker, "SessionLocal", Session)
    monkeypatch.setattr(worker, "validate_permitted_page", lambda url: url)
    monkeypatch.setattr(worker, "fetch_bounded_text", lambda *args, **kwargs: "fixture")
    monkeypatch.setattr(PlatformAdapter, "extract", lambda self, html, url: {
        "title": "Phone X", "brand": None, "model": "PX-1", "identifiers": {"gtin": "1234567890123"},
        "specs": {"ram": "4GB"}, "image_url": None, "price": Decimal("700"), "currency": "INR",
        "price_type": "selling", "availability": "in_stock", "evidence": {}
    })
    worker.check_due_jobs()
    with Session() as db:
        assert db.scalar(select(AlertEvent).where(AlertEvent.kind == "price_drop")) is None
        assert len(list(db.scalars(select(Observation).where(Observation.listing_id == listing.id)))) == 1
    engine.dispose()
