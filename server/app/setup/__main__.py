"""Local wizard or scripted configuration, usable before the normal DB exists."""

import argparse
import getpass
import json
from pathlib import Path

from app.setup.schemas import SetupConfiguration
from app.setup.service import save_settings, check_capabilities


def main():
    parser = argparse.ArgumentParser(description="Configure Oracle's database and optional AI capabilities")
    parser.add_argument("--file", type=Path, help="Read a SetupConfiguration JSON file instead of interactive questions")
    parser.add_argument("--migrate", action="store_true", help="Apply Alembic migrations after a successful database connection")
    args = parser.parse_args()
    if args.file:
        data = SetupConfiguration.model_validate_json(args.file.read_text())
    else:
        database = getpass.getpass("PostgreSQL URL (leave blank to retain environment/current setting): ")
        inputs = {"database_url": database or None,
                  "database_mode": input("Database mode: bundled/existing [existing]: ").strip() or "existing"}
        for name in ("chat", "embeddings"):
            url = input(f"{name} endpoint URL (blank leaves this capability unconfigured): ").strip()
            if not url:
                continue
            model = input(f"{name} served model name: ").strip()
            endpoint = {"url": url, "model": model, "api_key": getpass.getpass("API key (blank for local unauthenticated endpoint): ") or None}
            if name == "embeddings":
                preset = input("Embedding preset: nomic/custom [nomic]: ").strip() or "nomic"
                endpoint["profile"] = {"model": model, "revision": input("Pinned weights/deployment revision: ").strip(),
                    "dimensions": 768 if preset == "nomic" else int(input("Vector dimensions: ")),
                    "document_prefix": "search_document: " if preset == "nomic" else input("Document task prefix (empty allowed): "),
                    "query_prefix": "search_query: " if preset == "nomic" else input("Query task prefix (empty allowed): ")}
            inputs[name] = endpoint
        data = SetupConfiguration.model_validate(inputs)
    print(json.dumps(save_settings(data), indent=2))
    if args.migrate:
        from app.database import create_db_engine
        from sqlalchemy import text
        engine = create_db_engine()
        with engine.connect() as db:
            db.execute(text("SELECT 1"))
        engine.dispose()
        from alembic import command
        from alembic.config import Config
        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
        command.upgrade(config, "head")
    print(json.dumps(check_capabilities(["database", "chat", "embeddings"]), indent=2))


if __name__ == "__main__":
    main()
