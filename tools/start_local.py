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
        # Match uvicorn's bind policy so TIME_WAIT does not look like a live API.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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


def registry_path(port: int) -> Path:
    """Return the private service registry for the selected local API port."""
    return ROOT / f'.local/run/services-{port}.json'


def managed_service(port: int) -> dict | None:
    """Read port's registry and verify its unique token against the actual supervisor process."""
    try:
        record = json.loads(registry_path(port).read_text())
        pid = int(record['pid'])
        if pid <= 1:
            return None
        import shlex
        command = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'command='],
                                 capture_output=True, text=True, timeout=2)
        words = shlex.split(command.stdout)
        if (str(ROOT / 'tools/start_local.py') in words and 'serve' in words and
                '--service-token' in words and words[words.index('--service-token') + 1] == record['token']):
            return record
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        pass
    return None


def serve(port: int = 8000, token: str = '') -> int:
    """Own API/worker services on port until stopped; token identifies this supervisor safely."""
    runtime = ROOT / '.local/run'
    logs = ROOT / '.local/logs'
    runtime.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    api = worker = None
    with ExitStack() as files:
        lock = files.enter_context((runtime / f'services-{port}.lock').open('a'))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise StartupError('Services are already managed on this port.') from None
        url = f'http://127.0.0.1:{port}'
        try:
            reuse_api = not available(port)
            if reuse_api:
                wait_api(url, None, timeout=2)
            postgres()
            if not reuse_api:
                migration_log = files.enter_context((logs / 'migrations.log').open('ab'))
                migration = subprocess.run([str(PYTHON), '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'server',
                                           stdout=migration_log, stderr=subprocess.STDOUT)
                if migration.returncode:
                    raise StartupError('Database migration failed. See .local/logs/migrations.log.')
                api_log = files.enter_context((logs / 'api.log').open('ab'))
                api = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)],
                                       cwd=ROOT / 'server', stdout=api_log, stderr=subprocess.STDOUT, start_new_session=True)
                wait_api(url, api)
            worker_log = files.enter_context((logs / 'worker.log').open('ab'))
            worker = subprocess.Popen([str(PYTHON), '-m', 'app.jobs.worker'], cwd=ROOT / 'server',
                                      stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True)
            time.sleep(.2)
            if worker.poll() is not None:
                raise StartupError('The worker stopped during startup. See .local/logs/worker.log.')
            record = {'pid': os.getpid(), 'token': token, 'port': port, 'owns_api': not reuse_api}
            temporary = registry_path(port).with_suffix('.tmp')
            temporary.write_text(json.dumps(record))
            temporary.chmod(0o600)
            temporary.replace(registry_path(port))
            print(f'Membrain services ready at {url}.', flush=True)
            while True:
                if (api is not None and api.poll() is not None) or worker.poll() is not None:
                    raise StartupError('A managed service stopped. See .local/logs/.')
                time.sleep(.5)
        except KeyboardInterrupt:
            return 0
        finally:
            stop(worker)
            stop(api)
            try:
                record = json.loads(registry_path(port).read_text())
                if record.get('token') == token:
                    registry_path(port).unlink()
            except (OSError, ValueError):
                pass
            print('Managed API/worker stopped. PostgreSQL remains running.', flush=True)


def ensure_services(port: int) -> None:
    """Connect to healthy services on port or start a detached supervisor once."""
    runtime = ROOT / '.local/run'
    logs = ROOT / '.local/logs'
    runtime.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    with (runtime / f'start-{port}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        url = f'http://127.0.0.1:{port}'
        if not available(port):
            wait_api(url, None, timeout=2)
            if fetch(url + '/health/ready').get('worker', {}).get('ready'):
                return
        record = managed_service(port)
        if record:
            wait_api(url, None)
            return
        from uuid import uuid4
        token = uuid4().hex
        with (logs / 'services.log').open('ab') as log:
            process = subprocess.Popen([str(PYTHON), str(ROOT / 'tools/start_local.py'), 'serve',
                                        '--port', str(port), '--service-token', token],
                                       cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        # An API can appear before the worker and registry. Wait for the complete stack.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise StartupError('Service startup failed. See .local/logs/services.log.')
            try:
                if registry_path(port).exists() and fetch(url + '/health/ready').get('worker', {}).get('ready'):
                    return
            except (OSError, ValueError):
                pass
            time.sleep(.2)
        process.terminate()
        raise StartupError('Services did not become ready. See .local/logs/services.log.')


def supervise(command: str = 'menu', port: int = 8000, no_setup: bool = False) -> int:
    """Ensure port's services persist independently, then open menu/setup with optional setup skip."""
    ensure_services(port)
    args = [str(PYTHON), '-m', 'membrain_cli', command, '--api-url', f'http://127.0.0.1:{port}']
    if no_setup:
        args.append('--no-setup')
    try:
        return subprocess.call(args, cwd=ROOT)
    except KeyboardInterrupt:
        return 130


def stop_services(port: int) -> int:
    """Stop only the verified supervisor owned by this checkout on port."""
    record = managed_service(port)
    if not record:
        print('No managed services found for this port; other processes were left running.')
        return 0
    os.kill(record['pid'], signal.SIGTERM)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and managed_service(port):
        time.sleep(.2)
    if managed_service(port):
        raise StartupError('Services are still stopping. Check status or .local/logs/services.log.')
    print('Membrain services stopped. PostgreSQL remains running.')
    return 0


def main(argv=None) -> int:
    """Parse argv or shell arguments for menu/setup, status, stop, or the internal service process."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['menu', 'setup', 'status', 'stop', 'serve'], nargs='?', default='menu')
    parser.add_argument('--port', type=int, default=8000, help='Local API port (default: 8000)')
    parser.add_argument('--no-setup', action='store_true', help='Skip automatic first-run setup in menu mode')
    parser.add_argument('--service-token', default='', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    def interrupted(_signal, _frame):
        raise KeyboardInterrupt
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    try:
        if args.command == 'stop':
            return stop_services(args.port)
        if args.command == 'status':
            try:
                ready = fetch(f'http://127.0.0.1:{args.port}/health/ready')
            except (OSError, ValueError):
                print('Membrain API is stopped or unavailable.')
                return 1
            print(f"API running; database ready: {ready['database']['ready']}; worker running: {ready['worker']['ready']}")
            return 0
        if args.command == 'serve':
            if not args.service_token:
                parser.error('serve is internal; run ./start to launch services')
            return serve(args.port, args.service_token)
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
