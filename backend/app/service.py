from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import ADAPTERS, PLATFORMS, adapter_for_url
from .config import settings
from .matching import match_product
from .models import DiscoveryCandidate, DiscoveryRun, Listing, Observation, PlatformDiscovery, Product, StockObservation
from .security import fetch_bounded_text, validate_permitted_page


def inspect_url(url: str, db: Session) -> dict:
    adapter = adapter_for_url(url)
    if not adapter:
        return {
            "source": {
                "platform": None,
                "status": "unsupported_platform",
                "message": "Use an HTTPS product URL from Amazon India, Flipkart, Shopsy, Myntra, Meesho, AJIO, or Croma.",
            },
            "product": None,
            "offers": [],
            "platforms": platform_status(),
        }
    try:
        validate_permitted_page(url)
        html = fetch_bounded_text(url, settings.max_response_bytes)
        data = adapter.extract(html, url)
    except Exception as exc:
        message = str(exc)
        if "robots rules disallow" in message.lower() or "403" in message or "429" in message:
            status = "blocked"
        elif "access rules could not be verified" in message.lower():
            status = "access_policy_unavailable"
        elif isinstance(exc, httpx.TimeoutException):
            status = "timeout"
        else:
            status = "parse_error"
        return {"source": {"platform": adapter.platform.key, "status": status, "message": message[:240]}, "product": None, "offers": [], "platforms": platform_status()}
    listing = db.scalar(select(Listing).where(Listing.platform == adapter.platform.key, Listing.url == url))
    if listing:
        product = db.get(Product, listing.product_id)
        product.origin_url, product.origin_platform = url, adapter.platform.key
        listing.title, listing.brand, listing.model = data["title"], data["brand"], data["model"]
        listing.image_url = data["image_url"]
        listing.identifiers, listing.specs = data["identifiers"], data["specs"]
    else:
        product = Product(title=data["title"], brand=data["brand"], model=data["model"], identifiers=data["identifiers"], specs=data["specs"], origin_url=url, origin_platform=adapter.platform.key)
        db.add(product)
        db.flush()
        listing = Listing(product_id=product.id, platform=adapter.platform.key, url=url, title=data["title"], brand=data["brand"], model=data["model"], identifiers=data["identifiers"], specs=data["specs"], image_url=data["image_url"])
        db.add(listing)
        db.flush()
    observation = Observation(listing_id=listing.id, price=data["price"], currency=data["currency"], price_type=data["price_type"], availability=data["availability"], status="success" if data["price"] else "partial", adapter_version=adapter.version, evidence=data["evidence"])
    db.add(observation)
    if data["availability"] != "unknown":
        db.add(StockObservation(listing_id=listing.id, availability=data["availability"], evidence=data["evidence"]))
    run = DiscoveryRun(product_id=product.id, status="searching")
    db.add(run)
    db.flush()
    for platform in PLATFORMS:
        is_source = platform.key == adapter.platform.key
        check = PlatformDiscovery(run_id=run.id, platform=platform.key,
                                  status="source_checked" if is_source else "searching",
                                  checked_at=observation.observed_at if is_source else None,
                                  message="Source listing checked; cross-listing discovery is skipped for this retailer." if is_source else None)
        db.add(check)
        db.flush()
        if is_source:
            db.add(DiscoveryCandidate(check_id=check.id, url=url, title=data["title"], brand=data["brand"], model=data["model"],
                                      identifiers=data["identifiers"], specs=data["specs"], image_url=data["image_url"],
                                      match_classification="exact", match_evidence={"evidence": ["user-submitted source URL"]},
                                      price=data["price"], currency=data["currency"], price_type=data["price_type"], availability=data["availability"],
                                      observed_at=observation.observed_at))
    db.commit()
    return {"product": {"id": product.id, "title": product.title, "brand": product.brand, "model": product.model, "identifiers": product.identifiers, "specs": product.specs, "origin_platform": product.origin_platform},
            "source": {"platform": adapter.platform.key, "status": observation.status, "observed_at": observation.observed_at},
            "offers": [{"id": listing.id, "listing_id": listing.id, "platform": listing.platform, "url": url, "title": listing.title, "image_url": data["image_url"], "price": data["price"], "currency": data["currency"], "price_type": data["price_type"], "availability": data["availability"], "observed_at": observation.observed_at, "freshness": "fresh", "status": observation.status, "match": {"classification": "exact", "evidence": ["user-submitted source listing"], "missing": [], "conflicts": []}}],
            "lowest_verified_offer": None, "platforms": platform_status(), "discovery_run_id": run.id}


def platform_status() -> list[dict]:
    return [{"key": p.key, "name": p.name, "inspection": "configured_unverified", "discovery": p.discovery_status,
             "discovery_note": p.discovery_note, "manual_search_url": f"https://www.{p.domains[0]}/"} for p in PLATFORMS]


def compare_saved_product(product_id: int, db: Session) -> dict:
    product = db.get(Product, product_id)
    if not product:
        return {"product": None, "offers": [], "lowest_verified_offer": None, "platforms": platform_status()}
    anchor = {"title": product.title, "model": product.model, "identifiers": product.identifiers, "specs": product.specs}
    offers = []
    for listing in db.scalars(select(Listing).where(Listing.product_id == product_id)).all():
        observation = db.scalar(select(Observation).where(Observation.listing_id == listing.id, Observation.status == "success", Observation.price.is_not(None), Observation.currency == "INR", Observation.price_type == "selling").order_by(Observation.observed_at.desc()).limit(1))
        if not observation:
            continue
        checked_at = observation.observed_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        freshness = "fresh" if datetime.now(timezone.utc) - checked_at <= timedelta(hours=24) else "stale"
        candidate = {"title": listing.title, "model": listing.model, "identifiers": listing.identifiers, "specs": listing.specs}
        match = {"classification": "exact", "evidence": ["user-submitted source listing"], "missing": [], "conflicts": []} if listing.url == product.origin_url else match_product(anchor, candidate)
        offers.append({"id": listing.id, "listing_id": listing.id, "platform": listing.platform, "url": listing.url, "title": listing.title, "image_url": listing.image_url, "price": observation.price, "currency": observation.currency, "price_type": observation.price_type, "availability": observation.availability, "observed_at": observation.observed_at, "freshness": freshness, "status": observation.status, "match": match})
    eligible = [o for o in offers if o["match"]["classification"] == "exact" and o["price"] is not None and o["price_type"] == "selling" and o["currency"] == "INR" and o["status"] == "success" and o["freshness"] == "fresh"]
    winner = min(eligible, key=lambda o: o["price"]) if eligible else None
    return {"product": {"id": product.id, "title": product.title, "brand": product.brand, "model": product.model, "identifiers": product.identifiers, "specs": product.specs, "origin_platform": product.origin_platform}, "offers": offers, "lowest_verified_offer": winner, "platforms": platform_status()}
