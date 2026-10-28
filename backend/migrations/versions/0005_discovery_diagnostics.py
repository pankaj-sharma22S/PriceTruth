"""Store structured retailer discovery diagnostics."""
from alembic import op
from sqlalchemy import Column, JSON, inspect, text

revision = "0005_discovery_diagnostics"
down_revision = "0004_alert_modes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns("platform_discoveries")}
    if "diagnostics" not in columns:
        op.add_column("platform_discoveries", Column("diagnostics", JSON(), nullable=False, server_default=text("'{}'")))


def downgrade():
    raise NotImplementedError("Destructive downgrade is disabled; use a reviewed backup/restore procedure.")
