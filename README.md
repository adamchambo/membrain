# Oracle

Oracle is an early-stage personal knowledge bank for recording what you understand as you learn, connecting it to familiar ideas, and revisiting it later. You explain a concept in your own words; AI may format that explanation for storage while preserving its meaning and uncertainty. Possible corrections and gaps are separate suggestions, not silent changes to your understanding. The intended experience also includes related concepts and review. Those product flows are still being shaped.

This repository contains a FastAPI server, PostgreSQL with pgvector, a background worker, and a small CLI. It supports conversational capture, automatic organization of user explanations, semantic retrieval, and a first cue-card review flow. Graphical clients, accounts, lessons, and broader learning workflows are still being shaped.

## Project layout

- `server/` — API and database code.
- `clients/` — a CLI and reserved desktop, mobile, and web entry points.
- `compose.yaml` — local server and database setup.
- `planning/` — local, Git-ignored working documents.

## Run locally

1. Create a root `.env` with `ORACLE_DB_PASSWORD` (see `.env.example`).
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:8000/health` to check the API. The route contracts and request parameters are shown at `http://127.0.0.1:8000/docs` (OpenAPI JSON: `/openapi.json`).

Docker Compose starts the API, worker, and database. It reads the ignored root `.env` and passes configuration to the API and worker. For a direct server run, load `DATABASE_URL` into the process environment, apply Alembic migrations, and run both `uvicorn app.main:app` and `python -m app.jobs.worker` from `server/`. Clients communicate through the API and need no database credentials.

The database is stored in a Docker volume so normal container restarts do not discard it. Capture saves your words immediately and queues organization; a topic introduction alone is context, not a learned explanation. Faithful formatting is banked automatically with provenance. You can inspect, revise, or undo it; suggested factual changes require a separate user decision.

Configure the optional chat-completions endpoint and model in `.env` for organization and review feedback. For embeddings, configure a compatible endpoint, served model/deployment revision, and dimensions (the selected default is Nomic at 768). The revision and preprocessing settings identify a vector profile; semantic search compares only that profile's current explanations. Work remains retryable when models are unavailable. No model weights are bundled or downloaded by the server.

From the repository root, start or resume a capture conversation:

```sh
python3 clients/cli/oracle.py chat
```

Say what you are learning, then add your understanding. `/show` inspects the latest capture, `/undo` retracts its latest derived learning, and `/new` starts a new conversation. The native quick-window interface is still planned. See [CLI usage](clients/cli/README.md) and [isolated database tests](server/tests/README.md).
