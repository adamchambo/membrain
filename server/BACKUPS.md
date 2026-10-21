# Portable banks and operational backups

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-10-19 | Define additive JSON portability and verify PostgreSQL recovery separately. |

## Portable JSON

Authenticated `GET /api/v1/bank/export` returns `membrain.bank.v1` JSON containing
user statements, histories, resources and uploaded source bytes, links, subjects,
review evidence, generated artifacts and suggestion decisions. Secrets in server
configuration, runtime jobs/leases, vectors and audio are excluded. User-written
content is exported verbatim; do not assume it has been scrubbed of secrets the
user themselves wrote.

`POST /api/v1/bank/import` takes `request_id` (UUID), `document`, and `preview`
(defaults true). Preview validates shape/types/IDs/reference closure and reports
counts. Database constraints are enforced atomically on actual import; a preview is
not a dry-run execution of every database rule. Import uses **copy-with-new-IDs**:
it never replaces existing records or merges concepts by title. It remaps relational
and structured provenance references, handles cyclic links in two passes, and rebuilds
derived work under the destination configuration. Identical retries with the same
request UUID return the original report; changed content conflicts.

Both operations are bounded to 10000 records and 32 MiB per bank document. Large
banks need an operational database backup. The export endpoint does not yet stream
an archive. Same document + a different request UUID creates another copy; clients
must retain the request UUID when retrying. Import untrusted user content only after
reviewing it; an import is not evidence of factual correctness.

## Full PostgreSQL backup

Use matching PostgreSQL client tools, and keep credentials in the ignored environment
or a private `.pgpass`. With standard `PGHOST`, `PGPORT`, `PGUSER`, `PGDATABASE` and
private password configuration, run:

```sh
pg_dump --format=custom --no-owner --no-acl --file /private/backup/membrain.dump
```

Back up the private Membrain configuration file separately with private permissions;
it contains provider credentials that are deliberately absent from portable exports.
Record the PostgreSQL/pgvector versions and application revision alongside backups.

To restore, stop application writers, create an **empty recovery database** with
pgvector available, set `PGDATABASE` to that recovery database, and run:

```sh
pg_restore --no-owner --no-acl --exit-on-error --dbname "$PGDATABASE" /private/backup/membrain.dump
```

Check the restored migration revision, inspect explanations/resources and validate
counts before pointing the stopped API and worker at it. Restart both together.
An interrupted worker lease expires and is reclaimable; avoid running a recovery
copy with live external providers until its configuration is intentionally selected.
Never use `--clean` against the only copy of a bank as a recovery shortcut.

The isolated test runner verifies a real custom-format dump/restore into a second
temporary database and compares every mapped table's contents. This proves the
local backup mechanics for the test bank, not an off-device backup or production
recovery time guarantee. Migrations also exercise downgrade/upgrade on disposable
data; downgrading feature migrations discards their feature tables and is not a
routine rollback strategy for a populated bank.
