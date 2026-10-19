"""Create, migrate, test, and remove one disposable oracle_test_* database.

ORACLE_TEST_ADMIN_URL must point to a PostgreSQL role allowed to create databases.
The live Oracle database is never a fixture target.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def main():
    admin_url = os.environ.get("ORACLE_TEST_ADMIN_URL")
    if not admin_url:
        raise SystemExit("Set ORACLE_TEST_ADMIN_URL to an admin connection used only for creating a disposable test database")
    name = "oracle_test_" + uuid4().hex
    url = make_url(admin_url)
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    quoted = engine.dialect.identifier_preparer.quote(name)
    cwd = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
           "ORACLE_TEST_DATABASE_URL": url.set(database=name).render_as_string(hide_password=False)}
    created = False
    try:
        with engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted}"))
            created = True
        for arguments in (["-m", "alembic", "upgrade", "head"],
                          ["-m", "alembic", "check"],
                          ["-m", "unittest", "discover", "-s", "tests", "-v"]):
            subprocess.run([sys.executable, *arguments], cwd=cwd, env=env, check=True)
        from backup_roundtrip import verify
        verify(admin_url, env["ORACLE_TEST_DATABASE_URL"])
        for arguments in (["-m", "alembic", "downgrade", "20261018_02"], ["-m", "alembic", "upgrade", "head"]):
            subprocess.run([sys.executable, *arguments], cwd=cwd, env=env, check=True)
    finally:
        if created:
            with engine.connect() as connection:
                connection.execute(text(f"DROP DATABASE {quoted} WITH (FORCE)"))
        engine.dispose()


if __name__ == "__main__":
    main()
