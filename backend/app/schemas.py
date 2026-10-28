from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, HttpUrl


class InspectRequest(BaseModel):
    url: HttpUrl


class TrackRequest(BaseModel):
    product_id: int
    target_price: Decimal | None = None
    mode: Literal["any_drop", "target_price"] | None = None
    listing_id: int | None = None


class TrackingUpdate(BaseModel):
    active: bool


class DiscoveryCandidateRequest(BaseModel):
    url: HttpUrl


class ListingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    platform: str
    url: str
    title: str
    match: dict
    price: Decimal | None
    currency: str | None
    availability: str
    observed_at: datetime | None
    status: str
