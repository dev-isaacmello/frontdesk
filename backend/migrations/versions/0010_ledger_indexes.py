"""Indexes for the sums that are now read on every turn and on the usage screen.

Revision ID: 0010
Revises: 0009
"""

from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    op.execute(
        """
        -- What a tenant spent this month, read at the start of each of its turns.
        create index model_calls_tenant_created on model_calls (tenant_id, created_at);
        -- The turns of a tenant in a period, for the owner's usage screen.
        create index turns_tenant_started on turns (tenant_id, started_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index turns_tenant_started;
        drop index model_calls_tenant_created;
        """
    )
