"""Initial enterprise schema with 15 tables for Private Telegram Assistant & Vault.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-01 22:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy Base.metadata.create_all is invoked by migration or entrypoint
    from app.core.database import Base
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from app.core.database import Base
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
