"""A message the channel refused is recorded as refused and not tried again.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    op.execute(
        """
        alter table messages add column send_error text;
        -- A delivery update names a message by the id its channel gave it.
        create index messages_provider_id on messages (tenant_id, provider_message_id)
            where provider_message_id is not null;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index messages_provider_id;
        alter table messages drop column send_error;
        """
    )
