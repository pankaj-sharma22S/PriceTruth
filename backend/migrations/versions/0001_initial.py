"""Initial PriceTruth schema.

Revision ID: 0001_initial
"""
from alembic import op
from app.db import Base
from app import models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    raise NotImplementedError("Destructive downgrade is disabled; use a reviewed backup/restore procedure.")
