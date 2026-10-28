"""Persist standalone stock observations and source platform identity.

Revision ID: 0002_stock_and_origin_platform
Revises: 0001_initial
"""
from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, inspect

revision = "0002_stock_and_origin_platform"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    inspector = inspect(op.get_bind())
    if "origin_platform" not in {col["name"] for col in inspector.get_columns("products") }:
        op.add_column("products", Column("origin_platform", String(40), nullable=True))
    if not inspector.has_table("stock_observations"):
        op.create_table(
            "stock_observations",
            Column("id", Integer, primary_key=True),
            Column("listing_id", Integer, ForeignKey("retailer_listings.id"), nullable=False),
            Column("availability", String(24), nullable=False),
            Column("observed_at", DateTime(timezone=True), nullable=False),
            Column("evidence", JSON, nullable=False),
        )
        op.create_index("ix_stock_observations_listing_id", "stock_observations", ["listing_id"])
        op.create_index("ix_stock_observations_observed_at", "stock_observations", ["observed_at"])


def downgrade():
    raise NotImplementedError("Destructive downgrade is disabled; use a reviewed backup/restore procedure.")
