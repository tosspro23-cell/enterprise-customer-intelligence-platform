# Phase Two Increment 03: PostgreSQL persistence boundary

Status: implementation increment; not enabled on the live AWS demo.

This increment introduces a PostgreSQL adapter behind the persistence port that
the live platform already uses. It is the persistence step in the Phase Two
sequence: the current EC2 demo remains on SQLite until the managed database is
provisioned, migrated, and accepted with retained business-data evidence.

## What changed

- `PersistenceStore` is now the application-facing storage contract.
- `SQLiteStore` remains the local/reference adapter and the current AWS demo
  adapter.
- `PostgresStore` implements the same trace, interaction, current-lineage,
  history, and deletion-tombstone contract.
- `DATABASE_URL` selects PostgreSQL at application startup. If it is absent,
  the application continues to use `DATABASE_PATH` and SQLite.
- PostgreSQL writes and deletion use explicit transactions plus a per-call
  advisory transaction lock. This protects post-call retry/delete races across
  processes for the durable records covered by this adapter.
- The container now includes the optional PostgreSQL runtime dependency, but no
  live deployment is changed by this increment.

## Contract and boundaries

The adapter intentionally preserves the current single-tenant data model. It
does not claim tenant isolation for shared PostgreSQL data, live-call recovery,
or distributed coordination of the in-memory `CallState`, `bindings`, and
per-call locks. Those are separate Phase Two increments.

The durable contract is deliberately narrow:

1. A post-call record is idempotent for the same call, transcript version,
   enrichment version, and content hash.
2. A conflicting content hash is rejected rather than silently replacing a
   derived result.
3. The current interaction pointer advances only to newer transcript/enrichment
   lineage; an older retry cannot roll it back.
4. A deletion tombstone is written in the same transaction that removes derived
   records, and later post-call writes for the call are rejected.
5. Trace upserts remain observable through the existing trace API.

## Verification

The normal deterministic suite continues to exercise the SQLite reference
adapter. The PostgreSQL contract tests run when `POSTGRES_TEST_DSN` is set:

```bash
POSTGRES_TEST_DSN='postgresql://postgres:postgres@127.0.0.1:55432/postgres' \
  pytest -q tests/integration/test_postgres_store.py
```

The acceptance evidence for this increment must include:

- a real PostgreSQL integration run for idempotency, lineage precedence,
  conflict rejection, tombstone anti-resurrection, trace visibility, and
  schema creation;
- the complete local suite and static checks;
- an application health response showing `persistence_backend: "postgres"` in
  a controlled local run;
- no `DATABASE_URL` change or cloud database provisioning in this PR.

## Next gate

Before moving the live demo or adding Fargate, define the authority boundary for
live state and prove cross-process coordination. A managed database alone does
not restore in-memory active calls or make a rolling deployment safe.
