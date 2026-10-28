from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(200))
    identifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    origin_url: Mapped[str | None] = mapped_column(Text)
    origin_platform: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    listings: Mapped[list["Listing"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Listing(Base):
    __tablename__ = "retailer_listings"
    __table_args__ = (UniqueConstraint("platform", "url", name="uq_listing_platform_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(200))
    identifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    product: Mapped[Product] = relationship(back_populates="listings")
    observations: Mapped[list["Observation"]] = relationship(back_populates="listing", cascade="all, delete-orphan")


class Observation(Base):
    __tablename__ = "price_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("retailer_listings.id"), index=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    price_type: Mapped[str] = mapped_column(String(32), default="unknown")
    availability: Mapped[str] = mapped_column(String(24), default="unknown")
    status: Mapped[str] = mapped_column(String(32), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    adapter_version: Mapped[str] = mapped_column(String(40), default="1")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    listing: Mapped[Listing] = relationship(back_populates="observations")


class StockObservation(Base):
    __tablename__ = "stock_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("retailer_listings.id"), index=True)
    availability: Mapped[str] = mapped_column(String(24))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class TrackingJob(Base):
    __tablename__ = "tracking_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    target_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mode: Mapped[str] = mapped_column(String(24), default="any_drop")
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("retailer_listings.id", name="fk_tracking_jobs_listing_id_retailer_listings"), nullable=True, index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=360)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracking_id: Mapped[int] = mapped_column(ForeignKey("tracking_jobs.id"), index=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("retailer_listings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    event_key: Mapped[str | None] = mapped_column(String(240), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="searching", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checks: Mapped[list["PlatformDiscovery"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class PlatformDiscovery(Base):
    __tablename__ = "platform_discoveries"
    __table_args__ = (UniqueConstraint("run_id", "platform", name="uq_discovery_run_platform"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("discovery_runs.id"), index=True)
    platform: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(32), default="searching", index=True)
    message: Mapped[str | None] = mapped_column(Text)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    manual_urls: Mapped[list] = mapped_column(JSON, default=list)
    run: Mapped[DiscoveryRun] = relationship(back_populates="checks")
    candidates: Mapped[list["DiscoveryCandidate"]] = relationship(back_populates="check", cascade="all, delete-orphan")


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    __table_args__ = (UniqueConstraint("check_id", "url", name="uq_discovery_candidate_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("platform_discoveries.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(500))
    brand: Mapped[str | None] = mapped_column(String(160))
    model: Mapped[str | None] = mapped_column(String(200))
    identifiers: Mapped[dict] = mapped_column(JSON, default=dict)
    specs: Mapped[dict] = mapped_column(JSON, default=dict)
    image_url: Mapped[str | None] = mapped_column(Text)
    match_classification: Mapped[str] = mapped_column(String(24))
    match_evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    price_type: Mapped[str] = mapped_column(String(32), default="unknown")
    availability: Mapped[str] = mapped_column(String(24), default="unknown")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    check: Mapped[PlatformDiscovery] = relationship(back_populates="candidates")
