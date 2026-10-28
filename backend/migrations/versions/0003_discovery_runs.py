"""Persist retailer discovery runs and candidate observations.

Revision ID: 0003_discovery_runs
Revises: 0002_stock_and_origin_platform
"""
from alembic import op
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, inspect
from app.db import Base
from app import models  # noqa: F401

revision = "0003_discovery_runs"
down_revision = "0002_stock_and_origin_platform"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if "image_url" not in {col["name"] for col in inspector.get_columns("retailer_listings")}:
        op.add_column("retailer_listings", Column("image_url", Text(), nullable=True))
    for name in ("discovery_runs", "platform_discoveries", "discovery_candidates"):
        if not inspector.has_table(name):
            Base.metadata.tables[name].create(bind=bind)


def downgrade():
    raise NotImplementedError("Destructive downgrade is disabled; use a reviewed backup/restore procedure.")
