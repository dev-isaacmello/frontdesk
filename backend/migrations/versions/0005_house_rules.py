"""Owner rules as append-only versions, with the findings of each version.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"

TABLES = ("house_rules", "rule_findings")


def upgrade() -> None:
    op.execute(
        """
        -- A version is never edited. The newest one is in force, from the next turn on.
        create table house_rules (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            version integer not null,
            body text not null,
            created_at timestamptz not null,
            unique (tenant_id, version),
            unique (tenant_id, id)
        );

        -- Where a version contradicts the policy that is enforced in code. Shown to the
        -- owner; enforcement does not read this table.
        create table rule_findings (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            house_rules_id uuid not null,
            clause text not null check (clause in (
                'discount', 'price_outside_catalog', 'action_without_tool', 'outside_business'
            )),
            excerpt text not null,
            source text not null check (source in ('code', 'model')),
            foreign key (tenant_id, house_rules_id) references house_rules (tenant_id, id)
        );

        -- A model call can now belong to something other than a turn: checking a rule
        -- version is one. The ledger still records every call.
        alter table model_calls alter column turn_id drop not null;
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
    op.execute(
        """
        delete from model_calls where turn_id is null;
        alter table model_calls alter column turn_id set not null;
        drop table rule_findings;
        drop table house_rules;
        """
    )
