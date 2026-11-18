"""Actions that wait for the owner: the tenant's notice for late changes and the requests.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.execute(
        """
        -- Cancelling or moving a booking that starts within this many minutes needs the
        -- owner's approval. Null means no change needs it.
        alter table tenants add column late_change_minutes integer
            check (late_change_minutes is null or late_change_minutes > 0);

        create table approval_requests (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            conversation_id uuid not null,
            turn_id uuid not null,
            rule text not null check (rule in ('late_change')),
            -- The validated tool call that waits. It is validated again when it runs.
            tool text not null,
            arguments jsonb not null,
            status text not null default 'pending'
                check (status in ('pending', 'approved', 'rejected')),
            requested_at timestamptz not null,
            decided_at timestamptz,
            -- Set when the paused turn was taken up again with the decision.
            resumed_at timestamptz,
            unique (tenant_id, id),
            foreign key (tenant_id, conversation_id) references conversations (tenant_id, id),
            foreign key (tenant_id, turn_id) references turns (tenant_id, id)
        );
        create unique index approval_requests_one_pending on approval_requests (conversation_id)
            where status = 'pending';

        grant select, insert, update, delete on approval_requests to frontdesk_app;
        alter table approval_requests enable row level security;
        alter table approval_requests force row level security;
        create policy tenant_isolation on approval_requests
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table approval_requests;
        alter table tenants drop column late_change_minutes;
        """
    )
