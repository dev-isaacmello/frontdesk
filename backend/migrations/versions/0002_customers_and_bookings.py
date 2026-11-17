"""Customers and bookings.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"

TABLES = ("customers", "customer_identities", "schedule_blocks", "bookings")


def upgrade() -> None:
    op.execute(
        """
        create table customers (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            display_name text,
            created_at timestamptz not null default now(),
            unique (tenant_id, id)
        );

        -- Kept apart from customers because the identity a channel gives can change
        -- while the person stays the same.
        create table customer_identities (
            tenant_id uuid not null,
            channel text not null check (channel in ('webchat', 'whatsapp')),
            external_id text not null,
            customer_id uuid not null,
            phone text,
            primary key (tenant_id, channel, external_id),
            foreign key (tenant_id, customer_id) references customers (tenant_id, id)
        );

        create table schedule_blocks (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            resource_id uuid not null,
            during tstzrange not null check (not isempty(during)),
            reason text,
            foreign key (tenant_id, resource_id) references resources (tenant_id, id)
        );

        create index schedule_blocks_during on schedule_blocks using gist (resource_id, during);

        create table bookings (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            customer_id uuid not null,
            service_id uuid not null,
            resource_id uuid not null,
            during tstzrange not null check (not isempty(during)),
            status text not null default 'confirmed' check (status in ('confirmed', 'cancelled')),
            price_cents integer not null check (price_cents >= 0),
            idempotency_key text not null,
            created_at timestamptz not null default now(),
            cancelled_at timestamptz,
            unique (tenant_id, idempotency_key),
            foreign key (tenant_id, customer_id) references customers (tenant_id, id),
            foreign key (tenant_id, service_id) references services (tenant_id, id),
            foreign key (tenant_id, resource_id) references resources (tenant_id, id),
            -- The guarantee against double booking. The application checks first to give
            -- a useful answer, but two requests in flight are decided here.
            constraint bookings_no_overlap exclude using gist (
                tenant_id with =, resource_id with =, during with &&
            ) where (status = 'confirmed')
        );

        create index bookings_customer on bookings (tenant_id, customer_id);
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
