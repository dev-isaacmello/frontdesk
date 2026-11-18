"""What the owner's panel needs: owner accounts and sessions, the step timeline of a turn,
and messages written by the owner.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"


def upgrade() -> None:
    op.execute(
        """
        -- There is no signup. Owners come from the seed.
        create table users (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null references tenants (id),
            email text not null unique,
            name text not null,
            password_hash text not null,
            unique (tenant_id, id)
        );

        -- The panel's server holds the token in a cookie the browser cannot read. Only a
        -- hash of it is stored here.
        create table owner_sessions (
            id uuid primary key default uuidv7(),
            tenant_id uuid not null,
            user_id uuid not null,
            token_hash text not null unique,
            created_at timestamptz not null,
            expires_at timestamptz not null,
            foreign key (tenant_id, user_id) references users (tenant_id, id)
        );

        grant select, insert, update, delete on users, owner_sessions to frontdesk_app;
        -- Enabled but not forced, like channel_accounts and for the same reason: signing
        -- in happens before a tenant is known, through the two functions below, which run
        -- as the owner of the tables and return one row for one exact key.
        alter table users enable row level security;
        alter table owner_sessions enable row level security;
        create policy tenant_isolation on users
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));
        create policy tenant_isolation on owner_sessions
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));

        create function find_owner_by_email(p_email text)
        returns table (user_id uuid, tenant_id uuid, name text, password_hash text)
        language sql stable security definer set search_path = public
        begin atomic
            select u.id, u.tenant_id, u.name, u.password_hash from users u
            where u.email = lower(p_email);
        end;

        create function resolve_owner_session(p_token_hash text, p_now timestamptz)
        returns table (user_id uuid, tenant_id uuid)
        language sql stable security definer set search_path = public
        begin atomic
            select s.user_id, s.tenant_id from owner_sessions s
            where s.token_hash = p_token_hash and s.expires_at > p_now;
        end;

        revoke execute on function find_owner_by_email(text) from public;
        revoke execute on function resolve_owner_session(text, timestamptz) from public;
        grant execute on function find_owner_by_email(text) to frontdesk_app;
        grant execute on function resolve_owner_session(text, timestamptz) to frontdesk_app;

        -- The node timeline of a turn. The panel reads it, so the panel needs no tracing
        -- vendor. It holds names, durations and small outcomes, never customer text.
        create table turn_steps (
            tenant_id uuid not null,
            turn_id uuid not null,
            seq integer not null,
            node text not null,
            duration_ms integer not null,
            detail jsonb not null,
            primary key (turn_id, seq),
            foreign key (tenant_id, turn_id) references turns (tenant_id, id)
        );
        grant select, insert, update, delete on turn_steps to frontdesk_app;
        alter table turn_steps enable row level security;
        alter table turn_steps force row level security;
        create policy tenant_isolation on turn_steps
            using (tenant_id = (select app_tenant_id()))
            with check (tenant_id = (select app_tenant_id()));

        alter table turns add column blocked_drafts integer not null default 0;

        alter table messages drop constraint messages_author_check;
        alter table messages add constraint messages_author_check
            check (author in ('customer', 'agent', 'owner'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        delete from messages where author = 'owner';
        alter table messages drop constraint messages_author_check;
        alter table messages add constraint messages_author_check
            check (author in ('customer', 'agent'));
        alter table turns drop column blocked_drafts;
        drop table turn_steps;
        drop function resolve_owner_session(text, timestamptz);
        drop function find_owner_by_email(text);
        drop table owner_sessions;
        drop table users;
        """
    )
