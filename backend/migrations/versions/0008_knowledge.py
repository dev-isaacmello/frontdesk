"""The knowledge base of a tenant: short texts the owner knows and the catalog does not.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.execute(
        """
        create table kb_chunks (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            title text not null,
            body text not null,
            embedding vector(1536) not null,
            -- A vector is only comparable with vectors of the same model. A search made
            -- with another model does not read this row.
            embedding_model text not null,
            created_at timestamptz not null default now(),
            unique (tenant_id, title)
        );
        -- No approximate index on purpose. A tenant has tens of chunks, an exact scan of
        -- its own rows is a millisecond, and an approximate index shared by tenants is
        -- filtered after it is scanned, which loses results and lets the vectors of one
        -- tenant shape what another one finds.

        grant select, insert, update, delete on kb_chunks to frontdesk_app;
        alter table kb_chunks enable row level security;
        alter table kb_chunks force row level security;
        create policy tenant_isolation on kb_chunks
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));
        """
    )


def downgrade() -> None:
    op.execute("drop table kb_chunks")
