"""Persist alert mode, offer scope, and event deduplication key."""
from alembic import op
from sqlalchemy import Column, ForeignKey, Integer, String, inspect

revision = "0004_alert_modes"
down_revision = "0003_discovery_runs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("tracking_jobs")}
    missing = {"mode", "listing_id"} - columns
    if missing:
        recreate = "always" if bind.dialect.name == "sqlite" else "auto"
        with op.batch_alter_table("tracking_jobs", recreate=recreate) as batch:
            if "mode" in missing:
                batch.add_column(Column("mode", String(24), nullable=False, server_default="any_drop"))
            if "listing_id" in missing:
                batch.add_column(Column("listing_id", Integer(), ForeignKey("retailer_listings.id", name="fk_tracking_jobs_listing_id_retailer_listings"), nullable=True))
    else:
        indexes = {index["name"] for index in inspect(bind).get_indexes("tracking_jobs")}
        if "ix_tracking_jobs_listing_id" not in indexes:
            op.create_index("ix_tracking_jobs_listing_id", "tracking_jobs", ["listing_id"])
    op.execute("UPDATE tracking_jobs SET mode = 'target_price' WHERE target_price IS NOT NULL")

    event_columns = {column["name"] for column in inspect(bind).get_columns("alert_events")}
    if "event_key" not in event_columns:
        op.add_column("alert_events", Column("event_key", String(240), nullable=True))
    event_indexes = {index["name"] for index in inspect(bind).get_indexes("alert_events")}
    if "uq_alert_events_event_key" not in event_indexes:
        op.create_index("uq_alert_events_event_key", "alert_events", ["event_key"], unique=True)


def downgrade():
    raise NotImplementedError("Destructive downgrade is disabled; use a reviewed backup/restore procedure.")
