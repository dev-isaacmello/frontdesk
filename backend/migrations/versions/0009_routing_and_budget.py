"""Plans and monthly budgets of tenants, the deployment's daily spend and switch, and what
each outbound message cost on its channel.

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    op.execute(
        """
        alter table tenants
            add column plan text not null default 'basic' check (plan in ('basic', 'pro')),
            -- What the tenant's model calls may cost in a calendar month. Null is no limit.
            add column monthly_budget_microusd bigint
                check (monthly_budget_microusd is null or monthly_budget_microusd > 0);

        -- A channel charges in its own currency, so the amount is kept in it.
        alter table messages
            add column channel_cost_micros bigint,
            add column channel_cost_currency text;

        -- What every tenant together spent on models in a day. It holds one number per
        -- day and nothing of any tenant, because the application role cannot add up rows
        -- across tenants and should not be able to.
        create table deployment_spend (
            day date primary key,
            cost_microusd bigint not null
        );
        grant select, insert, update on deployment_spend to frontdesk_app;

        -- Switches of the whole deployment. The application reads them; changing one is
        -- an operator's act, made as the owner role.
        create table system_flags (
            name text primary key,
            enabled boolean not null,
            updated_at timestamptz not null default now()
        );
        insert into system_flags (name, enabled) values ('model_calls', true);
        grant select on system_flags to frontdesk_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table system_flags;
        drop table deployment_spend;
        alter table messages drop column channel_cost_micros, drop column channel_cost_currency;
        alter table tenants drop column plan, drop column monthly_budget_microusd;
        """
    )
