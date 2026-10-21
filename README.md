# Oracle

Oracle is an early-stage personal knowledge bank for recording what you understand as you learn, connecting it to familiar ideas, and revisiting it later. You explain a concept in your own words; AI may format that explanation for storage while preserving its meaning and uncertainty. Possible corrections and gaps are separate suggestions, not silent changes to your understanding. The intended experience also includes related concepts and review. Those product flows are still being shaped.

This repository contains a FastAPI server, PostgreSQL with pgvector, a background worker, and a small CLI. The API supports conversational capture, search, subject-scoped review, source uploads, learning suggestions and lessons, map data, and portable bank export/import. Graphical clients and hosted accounts remain future work. Real-model learning quality is still being evaluated.

## Project layout

- `server/` — API and database code.
- `clients/` — a CLI and reserved desktop, mobile, and web entry points.
- `compose.yaml` — local server and database setup.
- `planning/` — local, Git-ignored working documents.

## Start the existing native installation

From this checkout, run `./start`, or run `/Users/adam/projects/oracle/start` from
any directory. It loads `.env`, starts the existing native PostgreSQL cluster if
needed, applies migrations, starts the local API and a session worker, and opens
the interactive CLI. Logs go to ignored `.local/logs/`.

`./start setup` opens the wizard instead of the main menu. `--port 8001` selects a
different local API port; `--no-setup` skips automatic first-run setup. An existing
Oracle API on the selected port is reused, and its migrations are left alone.

Exiting the CLI or interrupting the launcher stops only API/worker processes owned
by that launcher. PostgreSQL remains running. Queued work remains saved for the next
worker run. The launcher uses this Mac's existing `.local/postgres` and `.venv`; it
doesn't create a new database or install packages. The Compose alternative below
uses a separate container database.

## Run locally with Docker

1. Create a root `.env` with `ORACLE_DB_PASSWORD` (see `.env.example`).
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:8000/health` to check the API. The route contracts and request parameters are shown at `http://127.0.0.1:8000/docs` (OpenAPI JSON: `/openapi.json`).

Docker Compose starts the API, worker, and database. It reads the ignored root `.env` and passes configuration to the API and worker. For a direct server run, load `DATABASE_URL` into the process environment, apply Alembic migrations, and run both `uvicorn app.main:app` and `python -m app.jobs.worker` from `server/`. Clients communicate through the API and need no database credentials.

The database is stored in a Docker volume so normal container restarts do not discard it. Capture saves your words immediately and queues organization; a topic introduction alone is context, not a learned explanation. Faithful formatting is banked automatically with provenance. You can inspect, revise, or undo it; suggested factual changes require a separate user decision.

Configure the optional chat-completions endpoint and model in `.env` for organization and review feedback. For embeddings, configure a compatible endpoint, served model/deployment revision, and dimensions (the selected default is Nomic at 768). The revision and preprocessing settings identify a vector profile; semantic search compares only that profile's current explanations. Work remains retryable when models are unavailable. No model weights are bundled or downloaded by the server.

Alternatively, run `python -m app.setup --migrate` from `server/` for the terminal
setup wizard. It saves private settings in ignored `.local/config.json`; nonempty
environment values take precedence. Compose shares a configuration volume between
the API and worker. `/health/ready` reports database migrations, worker heartbeat,
and work counts; explicit model probes are available through setup administration.
The current local API requires no client authentication. Compose publishes it on
`127.0.0.1:8000`. LLM provider keys stay in the server application settings;
clients do not need provider credentials for normal API calls.

Sources currently support uploaded UTF-8 TXT, Markdown, and HTML up to 2 MiB.
URL bookmarks do not fetch content automatically. Generated teaching content and
source excerpts remain separate from your banked explanations. Corrections require
a user decision and create a new revision. Review feedback compares recall to a
snapshot; it does not establish factual truth or mastery.

See [API operation notes](server/API.md), [backup and portability](server/BACKUPS.md),
and [local-model evaluation](server/evaluations/README.md). Voice transcription and
3D projection are deferred.

From the repository root, start or resume a capture conversation:

```sh
python3 clients/cli/oracle.py chat
```

Say what you are learning, then add your understanding. `/show` inspects the latest capture, `/undo` retracts its latest derived learning, and `/new` starts a new conversation. The native quick-window interface is still planned. See [CLI usage](clients/cli/README.md) and [isolated database tests](server/tests/README.md).

## Generated client SDKs

Python, Swift, and TypeScript clients share the exported OpenAPI contract.
See [generation and verification](tools/codegen/README.md) and the
[contract audit](contracts/AUDIT.md). Regenerate from the repository root:

```sh
.venv/bin/python tools/codegen/generate.py
.venv/bin/python tools/codegen/generate.py check
```

## Interactive CLI

Install the local client and generated SDK with
`.venv/bin/python -m pip install -e sdk/python -e clients/cli`, then run
`.venv/bin/oracle`. Run `.venv/bin/oracle setup` for configuration, or
`.venv/bin/oracle --stub` for an offline navigation demo.
See [CLI flows, settings and checks](clients/cli/README.md).
