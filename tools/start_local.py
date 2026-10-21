"""Supervise the native Membrain database, API, worker and interactive CLI."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/bin/python'


class StartupError(Exception):
    pass


def fetch(url: str) -> dict:
    """Read a local JSON endpoint at url, bounded to one second."""
    with urlopen(url, timeout=1) as response:
        return json.load(response)


def available(port: int) -> bool:
    """Return whether localhost port can be bound before starting the API."""
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def wait_api(url: str, process: subprocess.Popen | None, timeout: float = 30) -> None:
    """Wait up to timeout seconds for url; fail early if owned process exits."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise StartupError('The API stopped during startup. See .local/logs/api.log.')
        try:
            if fetch(url + '/health').get('status') == 'ok':
                schema = fetch(url + '/openapi.json')
                if schema.get('info', {}).get('title') not in ('Membrain API', 'Oracle API'):
                    raise StartupError('The selected port belongs to another service. Choose --port with a free port.')
                return
        except (URLError, OSError, ValueError):
            pass
        time.sleep(0.1)
    raise StartupError('The API did not become ready. See .local/logs/api.log.')


def stop(process: subprocess.Popen | None) -> None:
    """Gracefully stop owned process, escalating only if it fails to exit."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def postgres() -> None:
    """Start the already initialized native cluster when the configured URL needs it."""
    sys.path.insert(0, str(ROOT / 'server'))
    from app.database import database_url
    from app.errors import NotConfigured
    from sqlalchemy.exc import ArgumentError
    try:
        url = database_url()
    except (NotConfigured, ArgumentError, ValueError):
        raise StartupError('Set DATABASE_URL in the root .env before using the native launcher.') from None
    if url.host not in (None, 'localhost', '127.0.0.1', '::1'):
        print('Using the configured PostgreSQL server; no native cluster started.', flush=True)
        return
    cluster = ROOT / '.local/postgres'
    if not (cluster / 'PG_VERSION').exists():
        raise StartupError('Native PostgreSQL cluster is missing at .local/postgres. This launcher uses the existing local installation.')
    major = (cluster / 'PG_VERSION').read_text().strip()
    pg_ctl = shutil.which('pg_ctl')
    bundled = Path(f'/opt/homebrew/opt/postgresql@{major}/bin/pg_ctl')
    if bundled.exists():
        pg_ctl = str(bundled)
    if not pg_ctl:
        raise StartupError(f'Cannot find pg_ctl for PostgreSQL {major}.')
    status = subprocess.run([pg_ctl, '-D', str(cluster), 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if status.returncode == 0:
        print('PostgreSQL is already running.', flush=True)
        return
    if status.returncode != 3:
        raise StartupError('Could not inspect the existing PostgreSQL cluster; no database files were changed.')
    socket_directory = ROOT / '.local/run'
    socket_directory.mkdir(parents=True, exist_ok=True)
    port = url.port or 5432
    log = ROOT / '.local/postgres.log'
    options = f'-h 127.0.0.1 -p {port} -k "{socket_directory}"'
    result = subprocess.run([pg_ctl, '-D', str(cluster), '-l', str(log), '-o', options, '-w', 'start'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise StartupError('PostgreSQL failed to start. See .local/postgres.log.')
    print(f'PostgreSQL started on 127.0.0.1:{port}.', flush=True)


def supervise(command: str = 'menu', port: int = 8000, no_setup: bool = False) -> int:
    """Start the stack, run CLI command on port, optionally skipping automatic setup."""
    runtime = ROOT / '.local/run'
    logs = ROOT / '.local/logs'
    runtime.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    api = worker = cli = None
    with ExitStack() as files:
        lock = files.enter_context((runtime / 'launcher.lock').open('a'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartupError('Membrain is already open through this launcher. Use that session or open .venv/bin/membrain separately.') from None
        url = f'http://127.0.0.1:{port}'
        # Check the port before migrations or other startup work.
        reuse_api = not available(port)
        if reuse_api:
            wait_api(url, None, timeout=2)
            print(f'Using the Membrain API already running at {url}.', flush=True)
        postgres()
        try:
            migration_log = files.enter_context((logs / 'migrations.log').open('ab'))
            if not reuse_api:
                print('Checking database migrations...', flush=True)
                migration = subprocess.run([str(PYTHON), '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'server',
                                           stdout=migration_log, stderr=subprocess.STDOUT)
                if migration.returncode:
                    raise StartupError('Database migration failed. See .local/logs/migrations.log.')
                api_log = files.enter_context((logs / 'api.log').open('ab'))
                api = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=ROOT / 'server', stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True)
                wait_api(url, api)
                print(f'API ready at {url}.', flush=True)
            worker_log = files.enter_context((logs / 'worker.log').open('ab'))
            worker = subprocess.Popen([str(PYTHON), '-m', 'app.jobs.worker'], cwd=ROOT / 'server',
                                      stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)
            time.sleep(0.2)
            if worker.poll() is not None:
                raise StartupError('The worker stopped during startup. See .local/logs/worker.log.')
            print('Session worker started. Logs: .local/logs/', flush=True)
            arguments = [str(PYTHON), '-m', 'membrain_cli', command, '--api-url', url]
            if no_setup:
                arguments.append('--no-setup')
            cli = subprocess.Popen(arguments, cwd=ROOT)
            while cli.poll() is None:
                if api is not None and api.poll() is not None:
                    raise StartupError('API stopped. See .local/logs/api.log.')
                if worker.poll() is not None:
                    raise StartupError('Worker stopped. See .local/logs/worker.log.')
                try:
                    cli.wait(timeout=0.25)
                except subprocess.TimeoutExpired:
                    pass
            return cli.returncode
        except KeyboardInterrupt:
            if cli is not None and cli.poll() is None:
                cli.send_signal(signal.SIGINT)
                try:
                    cli.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            return 130
        finally:
            stop(cli)
            stop(worker)
            stop(api)
            print('Launcher-owned API/worker stopped. PostgreSQL remains running.', flush=True)


def main(argv=None) -> int:
    """Parse argv or process arguments; report startup failures without exposing settings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['menu', 'setup'], nargs='?', default='menu', help='Open the CLI menu or setup wizard')
    parser.add_argument('--port', type=int, default=8000, help='Local API port (default: 8000)')
    parser.add_argument('--no-setup', action='store_true', help='Skip automatic first-run setup in menu mode')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        return supervise(args.command, args.port, args.no_setup)
    except StartupError as error:
        print(f'Could not start Membrain: {error}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except (OSError, ImportError):
        print('Startup dependency failed. Check the project venv and .local/logs/.', file=sys.stderr)
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
