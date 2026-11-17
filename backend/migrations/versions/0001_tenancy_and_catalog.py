"""Tenancy and catalog.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

TABLES = (
    "tenants",
    "business_hours",
    "resources",
    "services",
    "service_resources",
    "service_prices",
)


def upgrade() -> None:
    op.execute(
        """
        -- Empty when unset or left over from a finished transaction: both mean no tenant.
        create function app_tenant_id() returns uuid
        language sql stable
        return nullif(current_setting('app.tenant_id', true), '')::uuid;

        create table tenants (
            id uuid primary key default uuidv7(),
            slug text not null unique,
            name text not null,
            timezone text not null,
            slot_minutes integer not null check (slot_minutes > 0),
            created_at timestamptz not null default now()
        );

        create table business_hours (
            tenant_id uuid not null references tenants (id),
            weekday smallint not null check (weekday between 1 and 7),
            opens time not null,
            closes time not null check (closes > opens),
            primary key (tenant_id, weekday)
        );

        create table resources (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            name text not null,
            kind text not null check (kind in ('professional', 'court')),
            unique (tenant_id, id),
            unique (tenant_id, name)
        );

        create table services (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            name text not null,
            duration_minutes integer not null check (duration_minutes > 0),
            unique (tenant_id, id),
            unique (tenant_id, name)
        );

        create table service_resources (
            tenant_id uuid not null,
            service_id uuid not null,
            resource_id uuid not null,
            primary key (service_id, resource_id),
            foreign key (tenant_id, service_id) references services (tenant_id, id),
            foreign key (tenant_id, resource_id) references resources (tenant_id, id)
        );

        create table service_prices (
            tenant_id uuid not null,
            service_id uuid not null,
            starts_at time not null,
            price_cents integer not null check (price_cents >= 0),
            primary key (service_id, starts_at),
            foreign key (tenant_id, service_id) references services (tenant_id, id)
        );
        """
    )
    for table in TABLES:
        tenant_column = "id" if table == "tenants" else "tenant_id"
        op.execute(
            f"""
            grant select, insert, update, delete on {table} to frontdesk_app;
            alter table {table} enable row level security;
            alter table {table} force row level security;
            -- The subquery makes the planner read the setting once per statement, not per row.
            create policy tenant_isolation on {table}
                using ({tenant_column} = (select app_tenant_id()))
                with check ({tenant_column} = (select app_tenant_id()));
            """
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"drop table {table}")
    op.execute("drop function app_tenant_id()")
