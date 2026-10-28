from datetime import datetime, timedelta, timezone
import logging
import time
import httpx
from concurrent.futures import ThreadPoolExecutor
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import delete, select

from .adapters import adapter_for_url
from .config import settings
from .matching import match_product
from .alert_rules import price_alert_kind
from .db import SessionLocal
from .discovery import discover_platform_candidates
from .models import AlertEvent, DiscoveryCandidate, DiscoveryRun, Listing, Observation, PlatformDiscovery, Product, StockObservation, TrackingJob
from .security import fetch_bounded_text, validate_permitted_page

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("pricetruth.worker")


def check_due_jobs():
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        jobs = db.scalars(select(TrackingJob).where(TrackingJob.active.is_(True), TrackingJob.next_run_at <= now)).all()
        total_successes = 0
        for job in jobs:
            job.last_checked_at = now
            job.last_error = None
            product = db.get(Product, job.product_id)
            if not product:
                job.last_error = "Tracked product no longer exists."
                continue
            listings_query = select(Listing).where(Listing.product_id == job.product_id)
            if job.listing_id is not None:
                listings_query = listings_query.where(Listing.id == job.listing_id)
            listings = db.scalars(listings_query).all()
            for listing in listings:
                adapter = adapter_for_url(listing.url)
                if not adapter:
                    continue
                anchor = {"title": product.title, "brand": product.brand, "model": product.model,
                          "identifiers": product.identifiers or {}, "specs": product.specs or {}}
                candidate = {"title": listing.title, "brand": listing.brand, "model": listing.model,
                             "identifiers": listing.identifiers or {}, "specs": listing.specs or {}}
                match = {"classification": "exact"} if listing.url == product.origin_url else match_product(anchor, candidate)
                if match["classification"] != "exact":
                    continue
                try:
                    validate_permitted_page(listing.url)
                    html = fetch_bounded_text(listing.url, settings.max_response_bytes)
                    data = adapter.extract(html, listing.url)
                    fresh_match = {"classification": "exact"} if listing.url == product.origin_url else match_product(anchor, data)
                    if fresh_match["classification"] != "exact":
                        job.last_error = "Current page data no longer verifies the tracked product variant."
                        continue
                    latest_price = db.scalar(select(Observation).where(
                        Observation.listing_id == listing.id, Observation.status == "success",
                        Observation.price.is_not(None), Observation.currency == "INR",
                        Observation.price_type == "selling").order_by(Observation.observed_at.desc()).limit(1))
                    latest_any = db.scalar(select(Observation).where(
                        Observation.listing_id == listing.id,
                        Observation.status.in_(("success", "partial"))).order_by(Observation.observed_at.desc()).limit(1))
                    obs = Observation(listing_id=listing.id, price=data["price"], currency=data["currency"],
                                      price_type=data["price_type"], availability=data["availability"],
                                      status="success" if data["price"] is not None else "partial",
                                      adapter_version=adapter.version, evidence=data["evidence"])
                    db.add(obs)
                    db.flush()
                    total_successes += 1
                    if data["availability"] != "unknown":
                        db.add(StockObservation(listing_id=listing.id, availability=data["availability"], evidence=data["evidence"]))

                    previous_price = latest_price.price if latest_price else None
                    if (obs.status == "success" and obs.currency == "INR" and obs.price_type == "selling"
                            and (job.listing_id is None or job.listing_id == listing.id)):
                        kind = price_alert_kind(job.mode, job.target_price, previous_price, obs.price)
                        if kind:
                            prev_id = latest_price.id if latest_price else "baseline"
                            event_key = f"price:{job.id}:{listing.id}:{kind}:{prev_id}:{obs.id}"
                            exists = db.scalar(select(AlertEvent.id).where(AlertEvent.event_key == event_key))
                            if not exists:
                                message = (f"Verified price dropped from INR {previous_price} to INR {obs.price}." if kind == "price_drop"
                                           else f"Verified price reached your INR {job.target_price} target at INR {obs.price}.")
                                db.add(AlertEvent(tracking_id=job.id, listing_id=listing.id, kind=kind,
                                                  message=message, event_key=event_key))
                    if (latest_any and latest_any.availability != "unknown" and data["availability"] != "unknown"
                            and latest_any.availability != data["availability"]):
                        transition = f"{latest_any.availability}_to_{data['availability']}"
                        event_key = f"stock:{job.id}:{listing.id}:{latest_any.id}:{obs.id}"
                        if not db.scalar(select(AlertEvent.id).where(AlertEvent.event_key == event_key)):
                            db.add(AlertEvent(tracking_id=job.id, listing_id=listing.id, kind="stock_change",
                                              message=f"Availability changed: {transition}", event_key=event_key))
                except Exception as exc:
                    log.warning("Check failed for listing %s: %s", listing.id, str(exc)[:240])
                    job.last_error = str(exc)[:500]
            job.next_run_at = now + timedelta(minutes=max(30, min(job.interval_minutes, 1440)))
        db.commit()
        log.info("Checked %s due tracking jobs; %s listings had successful observations", len(jobs), total_successes)

def process_discovery_runs():
    with SessionLocal() as db:
        runs = db.scalars(select(DiscoveryRun).where(DiscoveryRun.status == "searching").order_by(DiscoveryRun.created_at).limit(5)).all()
        for run in runs:
            product = db.get(Product, run.product_id)
            if not product:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
                continue
            source = {"title": product.title, "brand": product.brand, "model": product.model,
                      "identifiers": product.identifiers or {}, "specs": product.specs or {}, "origin_url": product.origin_url}
            checks = db.scalars(select(PlatformDiscovery).where(PlatformDiscovery.run_id == run.id, PlatformDiscovery.status == "searching").order_by(PlatformDiscovery.attempts, PlatformDiscovery.id)).all()
            checks = checks[:7]
            for check in checks:
                check.attempts += 1
            db.commit()
            source_results = {}
            deadline = time.monotonic() + settings.discovery_overall_timeout_seconds
            with ThreadPoolExecutor(max_workers=max(1, min(settings.discovery_concurrency, len(checks)))) as pool:
                futures = {check.id: pool.submit(discover_platform_candidates, check.platform, source, check.manual_urls or [], deadline) for check in checks}
                for check in checks:
                    try:
                        source_results[check.id] = futures[check.id].result()
                    except Exception as exc:
                        source_results[check.id] = {"status": "could_not_check", "message": str(exc)[:240], "candidates": []}
            for check in checks:
                db.execute(delete(DiscoveryCandidate).where(DiscoveryCandidate.check_id == check.id))
                result = source_results[check.id]
                check.checked_at = datetime.now(timezone.utc)
                check.message = result["message"]
                check.diagnostics = result.get("diagnostics", {})
                outcome = (result.get("diagnostics") or {}).get("outcome")
                retryable_incomplete = result["status"] == "could_not_check" or outcome == "discovery_incomplete"
                if retryable_incomplete and check.attempts < 2:
                    check.status = "searching"
                    check.message = (check.message + " Retry queued." if check.message else "Temporary failure. Retry queued.")
                elif outcome == "discovery_incomplete" and result["status"] == "no_match_found":
                    check.status = "could_not_check"
                else:
                    check.status = result["status"]
                for candidate in result["candidates"]:
                    if candidate["match"]["classification"] == "exact":
                        listing = db.scalar(select(Listing).where(Listing.platform == check.platform, Listing.url == candidate["url"]))
                        if listing is None:
                            listing = Listing(product_id=product.id, platform=check.platform, url=candidate["url"], title=candidate["title"],
                                              brand=candidate.get("brand"), model=candidate.get("model"), identifiers=candidate.get("identifiers", {}),
                                              specs=candidate.get("specs", {}), image_url=candidate.get("image_url"))
                            db.add(listing)
                            db.flush()
                        if listing.product_id == product.id:
                            listing.title, listing.brand, listing.model = candidate["title"], candidate.get("brand"), candidate.get("model")
                            listing.identifiers, listing.specs, listing.image_url = candidate.get("identifiers", {}), candidate.get("specs", {}), candidate.get("image_url")
                            db.add(Observation(listing_id=listing.id, price=candidate.get("price"), currency=candidate.get("currency"),
                                               price_type=candidate.get("price_type", "unknown"), availability=candidate.get("availability", "unknown"),
                                               status="success" if candidate.get("price") is not None else "partial", evidence=candidate.get("evidence", {})))
                            if candidate.get("availability") != "unknown":
                                db.add(StockObservation(listing_id=listing.id, availability=candidate["availability"], evidence=candidate.get("evidence", {})))
                    check.candidates.append(DiscoveryCandidate(
                        url=candidate["url"], title=candidate["title"], brand=candidate.get("brand"), model=candidate.get("model"),
                        identifiers=candidate.get("identifiers", {}), specs=candidate.get("specs", {}), image_url=candidate.get("image_url"),
                        match_classification=candidate["match"]["classification"], match_evidence=candidate["match"],
                        price=candidate.get("price"), currency=candidate.get("currency"), price_type=candidate.get("price_type", "unknown"),
                        availability=candidate.get("availability", "unknown"), observed_at=datetime.now(timezone.utc)))
                db.commit()
            remaining = db.scalar(select(PlatformDiscovery.id).where(PlatformDiscovery.run_id == run.id, PlatformDiscovery.status == "searching").limit(1))
            if not remaining:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                db.commit()
            log.info("Processed discovery run %s; state=%s", run.id, run.status)


if __name__ == "__main__":
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(check_due_jobs, "interval", seconds=30, max_instances=1, coalesce=True)
    scheduler.add_job(process_discovery_runs, "interval", seconds=5, max_instances=1, coalesce=True)
    scheduler.start()
