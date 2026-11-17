# 0004. Row-level security with a transaction-scoped tenant setting and one driver

Status: accepted

## Context

Tenant isolation has to hold when the application is wrong, including the retrieval path over pgvector. The services use an async connection pool, so whatever identifies the tenant must not survive on a connection after the request that set it.

Checked in docs/verificado.md: table owners and roles with `BYPASSRLS` skip policies unless the table has `FORCE ROW LEVEL SECURITY`; a table with RLS enabled and no policy denies everything; `set_config(name, value, true)` lasts for the current transaction only, while a plain `SET` persists on the session; SQLAlchemy's pool only issues a rollback when a connection is returned; unique and foreign key checks bypass RLS; RDS Proxy pins a PostgreSQL connection when a variable is set; PgBouncer in transaction mode does not support session `SET`.

## Decision

The runtime role is not the owner of the tables and cannot bypass RLS. Every tenant table has RLS enabled and forced, with one policy pair on `nullif(current_setting('app.tenant_id', true), '')::uuid`.

The tenant is set with `set_config('app.tenant_id', :id, true)` as the first statement of every transaction, from a single place: an `after_begin` listener on the session class, fed by a context variable that the request or the worker job sets. A transaction that begins without a tenant in the context sets nothing and therefore sees nothing.

Session-level `SET` is forbidden in the codebase and checked by a test that scans for it.

SQLAlchemy and the LangGraph checkpointer both use psycopg 3. One driver means one pooling behavior to reason about.

There is no connection pooler in front of the database at this size. Azure Database for PostgreSQL offers a built-in PgBouncer; if it is switched on later, the transaction-scoped setting is the form that survives transaction pooling, and that claim would need a test against it.

The isolation test in Phase 4 connects as the runtime role and tries, for each tenant table and for the retrieval query, to read and write the other tenant's rows with no tenant set, with the wrong tenant set, and with an explicit `WHERE tenant_id = :other`. All must return nothing or fail.

## Alternatives rejected

Filtering by tenant in every query. This is the thing RLS exists to back up; one forgotten filter is a leak.

Session-level setting, reset when the connection returns to the pool. It depends on a reset hook always running. A crash between set and reset leaves a connection carrying a tenant.

A schema or a database per tenant. Stronger isolation and simpler vector indexes, but migrations multiply by tenant and the project has two tenants and no onboarding flow.

A database role per tenant. Policies become simpler, connection pooling becomes per tenant.

## Cost of this choice

Every transaction pays one extra statement. Uniqueness is not protected by RLS: a unique constraint that spans tenants would let one tenant learn that a value exists in another, so every unique key built from a value that has meaning outside the system starts with `tenant_id`, and the two that do not (owner email, channel external id) are deliberate and listed in the data model. Keys made only of generated ids carry no such risk. The checkpointer tables are outside this scheme because the library creates them without a tenant column.

For retrieval, an approximate index shared by all tenants filters after the index scan, which can return fewer rows than asked and lets one tenant's vectors affect another's recall. With a few hundred chunks per tenant I start with exact search, no approximate index, and let the retrieval harness in Phase 4 say when that stops being enough.
