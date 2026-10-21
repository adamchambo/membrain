# Tests

Run pure output-validation tests with `python -m unittest discover -s tests -v`
from `server/`. Database cases skip unless `MEMBRAIN_TEST_DATABASE_URL` names an
explicitly disposable `membrain_test_*` database.

For the full suite, set `MEMBRAIN_TEST_ADMIN_URL` to a development PostgreSQL admin
connection and run `python tests/run_postgres.py`. This creates a unique disposable
database, applies all migrations, checks ORM drift, runs the suite, exercises the new
migrations' downgrade/upgrade path, and removes only that test database in `finally`.
It also uses `pg_dump` and `pg_restore` to restore a second disposable database and
compare all mapped table contents. Set `MEMBRAIN_PG_BIN` when the utilities are outside
PATH (the local fallback is Homebrew PostgreSQL 18).
The admin connection's existing database is never used for fixtures.

The suite covers immediate saving, topic-only messages, automatic multiple-concept
banking, idempotency, invalid sources/targets, optional clarification, undo, expired
worker fencing, vector profile/revision isolation, and saved review answers. A local
fake HTTP provider exercises transport through to vector retrieval. These checks
validate the processing mechanics; real model fidelity and retrieval quality need
evaluation with the configured models and representative user explanations.

Capability tests additionally cover private setup configuration and environment
precedence, archive/restore, versioned HTML extraction, subject quizzes and history,
source-citation rejection, explicit suggestion adoption, embedding-profile cutover,
portable preview/import/retry with circular provenance references, map metadata,
and permanent-deletion guards. Test configuration uses a temporary private file.

Conversation tests (`test_conversation.py`) drive `POST /turns` and the worker with a
scripted model that answers per prompt. They cover verbatim saving and idempotency,
automatic subjects and topic carry-forward, mixed bank-and-practice turns, private
multiple-choice keys graded by the stored key, recall that quotes saved words and
says when an analogy is missing, bank-wide gap ranking with need history, timezone
and period scope, relevance ordering, per-conversation ordering, checkpointed retries
that never repeat completed intents, adoption provenance, v2 export and v1 import,
and router corrections observed with the local model.

CLI SDK journeys also cover capture/search/review, real loopback HTTP transport,
possible-gap diagnostics and separate lessons, resource browsing, subject scope,
conversation pagination, local resume IDs, and partial provider configuration.
Install the local SDK/client packages before running these cases; the database
fixtures still require the disposable `membrain_test_*` guard.
