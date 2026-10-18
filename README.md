# Oracle

Oracle is an early-stage personal knowledge bank for recording what you understand as you learn, connecting it to familiar ideas, and revisiting it later. You explain a concept in your own words; AI may format that explanation for storage while preserving its meaning and uncertainty. Possible corrections and gaps are separate suggestions, not silent changes to your understanding. The intended experience also includes related concepts and review. Those product flows are still being shaped.

This repository contains a small FastAPI server, PostgreSQL with pgvector, an initial data schema, and reserved client folders. It does **not** yet implement concept capture, AI, accounts, or review flows.

## Project layout

- `server/` — API and database code.
- `clients/` — CLI, desktop, mobile, and web entry points. These are stubs while the first frontend is being decided.
- `compose.yaml` — local server and database setup.
- `planning/` — local, Git-ignored working documents.

## Run the local scaffold

1. Create a root `.env` with `ORACLE_DB_PASSWORD` (see `.env.example`).
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:8000/health` to check the API. FastAPI's API docs are at `http://127.0.0.1:8000/docs`.

Docker Compose reads the ignored root `.env` and passes a `DATABASE_URL` connection string to the API; FastAPI and Alembic parse that same environment variable. For a direct server run, set `DATABASE_URL` in its process environment. Client stubs have no database credentials and will communicate through the API.

The database is stored in a Docker volume so normal container restarts do not discard it. Migrations enable pgvector and create the initial capture, knowledge, vector, and review tables. No external AI key is required for this scaffold.
