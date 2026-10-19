# Tests

Run pure output-validation tests with `python -m unittest discover -s tests -v`
from `server/`. Database cases skip unless `ORACLE_TEST_DATABASE_URL` names an
explicitly disposable `oracle_test_*` database.

For the full suite, set `ORACLE_TEST_ADMIN_URL` to a development PostgreSQL admin
connection and run `python tests/run_postgres.py`. This creates a unique disposable
database, applies all migrations, checks ORM drift, runs the suite, exercises the new
migrations' downgrade/upgrade path, and removes only that test database in `finally`.
The admin connection's existing database is never used for fixtures.

The suite covers immediate saving, topic-only messages, automatic multiple-concept
banking, idempotency, invalid sources/targets, optional clarification, undo, expired
worker fencing, vector profile/revision isolation, and saved review answers. A local
fake HTTP provider exercises transport through to vector retrieval. These checks
validate the processing mechanics; real model fidelity and retrieval quality need
evaluation with the configured models and representative user explanations.
