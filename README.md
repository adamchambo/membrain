# Oracle

Oracle is an early-stage personal knowledge bank for recording what you learn, connecting it to what you already understand, and revisiting it later. The intended experience includes natural-language capture, clarifications, related concepts, and review. Those product flows are still being shaped.

This repository currently contains a small FastAPI server, a local PostgreSQL setup with pgvector, and reserved client folders. It does **not** yet implement concept capture, AI, accounts, or review.

## Project layout

- `server/` — API and database code.
- `clients/` — CLI, desktop, mobile, and web entry points. These are stubs while the first frontend is being decided.
- `compose.yaml` — local server and database setup.
- `planning/` — local, Git-ignored working documents.

## Run the local scaffold

1. Copy `.env.example` to `.env` and set a local database password.
2. Run `docker compose up --build`.
3. Open `http://127.0.0.1:8000/health` to check the API. FastAPI's API docs are at `http://127.0.0.1:8000/docs`.

The database is stored in a Docker volume so normal container restarts do not discard it. The first migration enables pgvector. No external AI key is required for this scaffold.
