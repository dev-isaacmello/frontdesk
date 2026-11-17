"""Handoff to a person, the conversation lease, and turns that do not complete.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"


def upgrade() -> None:
    op.execute(
        """
        alter table conversations
            add column mode text not null default 'agent' check (mode in ('agent', 'handoff')),
            -- Grows each time a worker takes the conversation. A turn's final write names
            -- the epoch it started under, so a worker that lost the lease cannot commit.
            add column lease_epoch bigint not null default 0,
            add column lease_until timestamptz;

        alter table turns drop constraint turns_status_check;
        alter table turns add constraint turns_status_check
            check (status in ('running', 'awaiting_approval', 'completed', 'failed'));

        create table handoffs (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            conversation_id uuid not null,
            turn_id uuid,
            reason text not null check (reason in (
                'customer_asked', 'agent_failed', 'guardrail_blocked', 'turn_limit',
                'budget_exhausted'
            )),
            opened_at timestamptz not null,
            resolved_at timestamptz,
            foreign key (tenant_id, conversation_id) references conversations (tenant_id, id),
            foreign key (tenant_id, turn_id) references turns (tenant_id, id)
        );
        create unique index handoffs_one_open on handoffs (conversation_id)
            where resolved_at is null;

        grant select, insert, update, delete on handoffs to frontdesk_app;
        alter table handoffs enable row level security;
        alter table handoffs force row level security;
        create policy tenant_isolation on handoffs
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table handoffs;

        update turns set status = 'completed' where status not in ('running', 'completed');
        alter table turns drop constraint turns_status_check;
        alter table turns add constraint turns_status_check
            check (status in ('running', 'completed'));

        alter table conversations
            drop column mode, drop column lease_epoch, drop column lease_until;
        """
    )
