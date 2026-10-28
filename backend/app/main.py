from datetime import datetime, timedelta, timezone
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from .adapters import PLATFORMS, adapter_for_url
from .config import settings
from .db import get_db
from .models import AlertEvent, DiscoveryCandidate, DiscoveryRun, Listing, Observation, PlatformDiscovery, Product, TrackingJob
from .schemas import DiscoveryCandidateRequest, InspectRequest, TrackRequest, TrackingUpdate
from .service import compare_saved_product, inspect_url, platform_status
from .matching import match_product
from .security import validate_public_product_url


app = FastAPI(title="PriceTruth AI", version="1.0.0", description="Evidence-based Indian retailer price comparison and tracking")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    # Vite binds to 0.0.0.0 and may be opened through the machine LAN IP.
    # Keep the regex limited to local development hosts and port 5173.
    allow_origin_regex=r"^https?://(?:localhost|127\.0\.0\.1|\d{1,3}(?:\.\d{1,3}){3}):5173$",
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ok"}


@app.get("/api/platforms")
def platforms():
    return {"platforms": platform_status()}


@app.post("/api/products/inspect")
def inspect(body: InspectRequest, db: Session = Depends(get_db)):
    result = inspect_url(str(body.url), db)
    if result["product"] is None:
        raise HTTPException(status_code=422, detail={"source": result["source"], "platforms": result["platforms"]})
    return result


@app.get("/api/discovery/{run_id}")
def discovery_status(run_id: int, db: Session = Depends(get_db)):
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Discovery run not found")
    checks = db.scalars(select(PlatformDiscovery).where(PlatformDiscovery.run_id == run_id).order_by(PlatformDiscovery.id)).all()
    now = datetime.now(timezone.utc)
    results = []
    for check in checks:
        candidates = db.scalars(select(DiscoveryCandidate).where(DiscoveryCandidate.check_id == check.id).order_by(DiscoveryCandidate.id)).all()
        results.append({"platform": check.platform, "status": check.status, "message": check.message, "diagnostics": check.diagnostics or {},
                        "attempts": check.attempts, "checked_at": check.checked_at,
                        "candidates": [{"id": c.id, "platform": check.platform, "url": c.url, "title": c.title, "brand": c.brand, "model": c.model,
                                        "identifiers": c.identifiers, "specs": c.specs, "image_url": c.image_url,
                                        "match_classification": c.match_classification, "match_evidence": c.match_evidence,
                                        "listing_id": db.scalar(select(Listing.id).where(Listing.product_id == run.product_id, Listing.url == c.url)),
                        "price": c.price, "currency": c.currency, "price_type": c.price_type,
                                        "availability": c.availability, "observed_at": c.observed_at,
                                        "freshness": "fresh" if (now - (c.observed_at.replace(tzinfo=c.observed_at.tzinfo or timezone.utc)) <= timedelta(hours=24)) else "stale"} for c in candidates]})
    exact = [candidate for result in results for candidate in result["candidates"]
             if candidate["match_classification"] == "exact" and candidate["price"] is not None
             and candidate["currency"] == "INR" and candidate["price_type"] == "selling" and candidate["freshness"] == "fresh"]
    winner = min(exact, key=lambda c: c["price"]) if exact else None
    return {"id": run.id, "product_id": run.product_id, "status": run.status, "created_at": run.created_at,
            "completed_at": run.completed_at, "checks": results, "lowest_verified_offer": winner}


@app.post("/api/discovery/{run_id}/candidates")
def add_discovery_candidate(run_id: int, body: DiscoveryCandidateRequest, db: Session = Depends(get_db)):
    run = db.get(DiscoveryRun, run_id)
    if not run:
        raise HTTPException(404, "Discovery run not found")
    adapter = adapter_for_url(str(body.url))
    if not adapter:
        raise HTTPException(422, "Candidate URL must belong to one of the configured retailer platforms.")
    check = db.scalar(select(PlatformDiscovery).where(PlatformDiscovery.run_id == run_id, PlatformDiscovery.platform == adapter.platform.key))
    if not check:
        raise HTTPException(404, "Platform check not found")
    candidate_url = str(body.url)
    try:
        validate_public_product_url(candidate_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if candidate_url not in (check.manual_urls or []) and len(check.manual_urls or []) < 5:
        check.manual_urls = [*(check.manual_urls or []), candidate_url]
    elif candidate_url not in (check.manual_urls or []):
        raise HTTPException(429, "This platform already has the maximum number of candidate URLs for this run.")
    check.status, check.attempts, check.message = "searching", 0, "Checking user-provided product link."
    run.status, run.completed_at = "searching", None
    db.commit()
    return {"run_id": run.id, "platform": check.platform, "status": check.status}


@app.get("/api/products/{product_id}")
def product(product_id: int, db: Session = Depends(get_db)):
    result = compare_saved_product(product_id, db)
    if result["product"] is None:
        raise HTTPException(404, "Product not found")
    latest_run = db.scalar(select(DiscoveryRun).where(DiscoveryRun.product_id == product_id).order_by(DiscoveryRun.created_at.desc()).limit(1))
    result["discovery_run_id"] = latest_run.id if latest_run else None
    return result


@app.get("/api/products/{product_id}/history")
def history(product_id: int, db: Session = Depends(get_db)):
    rows = db.execute(select(Observation, Listing).join(Listing).where(Listing.product_id == product_id, Observation.price.is_not(None), Observation.status == "success").order_by(Observation.observed_at)).all()
    return {"observations": [{"platform": l.platform, "url": l.url, "price": o.price, "currency": o.currency, "availability": o.availability, "observed_at": o.observed_at} for o, l in rows]}


@app.post("/api/tracking")
def create_tracking(body: TrackRequest, db: Session = Depends(get_db)):
    product = db.get(Product, body.product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    mode = body.mode or ("target_price" if body.target_price is not None else "any_drop")
    if mode == "target_price":
        value = body.target_price
        if value is None or not value.is_finite() or value <= 0 or value > 9999999999.99 or value.as_tuple().exponent < -2:
            raise HTTPException(422, "Target price must be a positive INR amount with at most two decimal places.")
    elif body.target_price is not None:
        raise HTTPException(422, "Any-price-drop alerts do not take a target price.")
    listing = None
    if body.listing_id is not None:
        listing = db.get(Listing, body.listing_id)
        if not listing or listing.product_id != product.id:
            raise HTTPException(422, "The offer does not belong to this product.")
        anchor = {"title": product.title, "brand": product.brand, "model": product.model,
                  "identifiers": product.identifiers or {}, "specs": product.specs or {}}
        candidate = {"title": listing.title, "brand": listing.brand, "model": listing.model,
                     "identifiers": listing.identifiers or {}, "specs": listing.specs or {}}
        match = {"classification": "exact"} if listing.url == product.origin_url else match_product(anchor, candidate)
        if match["classification"] != "exact":
            raise HTTPException(422, "Price alerts require a verified exact product and variant match.")
    duplicate = db.scalar(select(TrackingJob).where(
        TrackingJob.product_id == product.id, TrackingJob.listing_id == body.listing_id,
        TrackingJob.mode == mode, TrackingJob.target_price == body.target_price,
        TrackingJob.active.is_(True)).limit(1))
    if duplicate:
        job = duplicate
    else:
        job = TrackingJob(product_id=product.id, listing_id=body.listing_id, mode=mode, target_price=body.target_price)
        db.add(job)
        db.commit()
        db.refresh(job)
    return {"id": job.id, "product_id": job.product_id, "listing_id": job.listing_id,
            "active": job.active, "mode": job.mode, "target_price": job.target_price,
            "last_checked_at": job.last_checked_at, "next_run_at": job.next_run_at}


@app.get("/api/tracking")
def list_tracking(db: Session = Depends(get_db)):
    jobs = db.scalars(select(TrackingJob).order_by(TrackingJob.id.desc())).all()
    return {"tracking": [{"id": j.id, "product_id": j.product_id, "listing_id": j.listing_id,
                           "active": j.active, "mode": j.mode, "target_price": j.target_price,
                           "last_checked_at": j.last_checked_at, "next_run_at": j.next_run_at,
                           "last_error": j.last_error} for j in jobs]}


@app.patch("/api/tracking/{tracking_id}")
def update_tracking(tracking_id: int, body: TrackingUpdate, db: Session = Depends(get_db)):
    job = db.get(TrackingJob, tracking_id)
    if not job:
        raise HTTPException(404, "Tracking job not found")
    job.active = body.active
    db.commit()
    return {"id": job.id, "active": job.active, "next_run_at": job.next_run_at}


@app.get("/api/tracking/{tracking_id}/status")
def tracking_status(tracking_id: int, db: Session = Depends(get_db)):
    job = db.get(TrackingJob, tracking_id)
    if not job:
        raise HTTPException(404, "Tracking job not found")
    return {"id": job.id, "active": job.active, "mode": job.mode, "listing_id": job.listing_id, "target_price": job.target_price, "last_checked_at": job.last_checked_at, "next_run_at": job.next_run_at, "last_error": job.last_error}


@app.get("/api/alerts")
def alerts(db: Session = Depends(get_db)):
    rows = db.scalars(select(AlertEvent).order_by(AlertEvent.created_at.desc()).limit(100)).all()
    return {"alerts": [{"id": a.id, "tracking_id": a.tracking_id, "listing_id": a.listing_id, "kind": a.kind, "message": a.message, "created_at": a.created_at} for a in rows]}
