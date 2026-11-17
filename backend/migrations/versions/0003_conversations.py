"""Channel accounts, inbox, conversations, turns and the model call ledger.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

TABLES = ("conversations", "inbound_events", "turns", "messages", "model_calls")


def upgrade() -> None:
    op.execute(
        """
        create table channel_accounts (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            channel text not null check (channel in ('webchat', 'whatsapp')),
            external_id text not null,
            unique (channel, external_id),
            unique (tenant_id, id)
        );

        grant select, insert, update, delete on channel_accounts to frontdesk_app;
        -- Enabled but not forced: the application role is confined to its tenant, while
        -- the function below, which runs as the owner, can read every account. It is the
        -- only way to find a tenant before one is set, and it returns two ids.
        alter table channel_accounts enable row level security;
        create policy tenant_isolation on channel_accounts
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));

        create function resolve_channel_account(p_channel text, p_external_id text)
        returns table (tenant_id uuid, channel_account_id uuid)
        language sql stable security definer set search_path = public
        begin atomic
            select a.tenant_id, a.id from channel_accounts a
            where a.channel = p_channel and a.external_id = p_external_id;
        end;

        revoke execute on function resolve_channel_account(text, text) from public;
        grant execute on function resolve_channel_account(text, text) to frontdesk_app;

        create table conversations (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            channel_account_id uuid not null,
            customer_id uuid not null,
            last_inbound_at timestamptz not null,
            created_at timestamptz not null default now(),
            unique (tenant_id, id),
            unique (tenant_id, channel_account_id, customer_id),
            foreign key (tenant_id, channel_account_id) references channel_accounts (tenant_id, id),
            foreign key (tenant_id, customer_id) references customers (tenant_id, id)
        );

        -- The idempotency gate of ingestion: one row per provider message, as received.
        create table inbound_events (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            channel_account_id uuid not null,
            provider_message_id text not null,
            raw jsonb not null,
            received_at timestamptz not null default now(),
            unique (channel_account_id, provider_message_id),
            unique (tenant_id, id),
            foreign key (tenant_id, channel_account_id) references channel_accounts (tenant_id, id)
        );

        create table turns (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            conversation_id uuid not null,
            status text not null default 'running' check (status in ('running', 'completed')),
            outcome text,
            started_at timestamptz not null,
            finished_at timestamptz,
            unique (tenant_id, id),
            foreign key (tenant_id, conversation_id) references conversations (tenant_id, id)
        );

        create unique index turns_one_running on turns (conversation_id) where status = 'running';

        -- Inbound rows are the inbox, outbound rows are the outbox.
        create table messages (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            conversation_id uuid not null,
            direction text not null check (direction in ('in', 'out')),
            author text not null check (author in ('customer', 'agent')),
            body text not null,
            occurred_at timestamptz not null,
            turn_id uuid,
            inbound_event_id uuid,
            seq integer,
            sent_at timestamptz,
            provider_message_id text,
            created_at timestamptz not null default now(),
            unique (turn_id, seq),
            unique (inbound_event_id),
            foreign key (tenant_id, conversation_id) references conversations (tenant_id, id),
            foreign key (tenant_id, turn_id) references turns (tenant_id, id),
            foreign key (tenant_id, inbound_event_id) references inbound_events (tenant_id, id)
        );

        create index messages_conversation on messages (conversation_id, occurred_at, id);
        create index messages_outbox on messages (conversation_id)
            where direction = 'out' and sent_at is null;

        create table model_calls (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            turn_id uuid not null,
            node text not null,
            provider text not null,
            model text not null,
            input_tokens integer not null,
            output_tokens integer not null,
            cache_read_tokens integer not null,
            cache_write_tokens integer not null,
            latency_ms integer not null,
            cost_microusd bigint not null,
            price_table_version text not null,
            created_at timestamptz not null default now(),
            foreign key (tenant_id, turn_id) references turns (tenant_id, id)
        );

        create index model_calls_turn on model_calls (turn_id);
        """
    )
    for table in TABLES:
        op.execute(
            f"""
            grant select, insert, update, delete on {table} to frontdesk_app;
            alter table {table} enable row level security;
            alter table {table} force row level security;
            create policy tenant_isolation on {table}
                using (tenant_id = (select app_tenant_id()))
                with check (tenant_id = (select app_tenant_id()));
            """
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"drop table {table}")
    op.execute("drop function resolve_channel_account(text, text)")
    op.execute("drop table channel_accounts")
