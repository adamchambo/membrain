"""Only server addresses and resumable IDs are stored on the client."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from uuid import UUID
from .types import ClientError, Context, Job


def server_url(value: str) -> str:
    """Validate value as an HTTP(S) server address without embedded credentials."""
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ClientError('Use an HTTP(S) server URL without credentials, query parameters, or fragments.')
    return value.rstrip('/')


def local_timezone() -> str:
    """IANA zone used by the server for "today" or "last week": TZ, then /etc/localtime, else UTC."""
    name = os.getenv('TZ', '').lstrip(':')
    if not name:
        target = os.path.realpath('/etc/localtime')
        name = target.split('/zoneinfo/', 1)[1] if '/zoneinfo/' in target else ''
    return name or 'UTC'


class Store:
    def __init__(self, path: Path | None = None):
        """Use path for client state; default to MEMBRAIN_CLI_STATE_FILE or XDG state."""
        state_root = Path(os.getenv('XDG_STATE_HOME', str(Path.home() / '.local/state')))
        override = os.getenv('MEMBRAIN_CLI_STATE_FILE') or os.getenv('ORACLE_CLI_STATE_FILE')
        self.path = path or Path(override or state_root / 'membrain/cli.json')
        source = self.path
        if path is None and not override and not source.exists():
            source = state_root / 'oracle/cli.json'
        try:
            self.data = json.loads(source.read_text()) if source.exists() else {}
            if not isinstance(self.data, dict) or not isinstance(self.data.get('servers', {}), dict) or any(not isinstance(value, dict) for value in self.data.get('servers', {}).values()):
                raise ValueError()
        except (ValueError, OSError) as error:
            raise ClientError(f'Cannot read CLI state at {self.path}; move it aside to start fresh.') from error

    @property
    def api_url(self) -> str:
        return server_url(os.getenv('MEMBRAIN_API_URL') or os.getenv('ORACLE_API_URL') or self.data.get('api_url') or 'http://127.0.0.1:8000')

    def entry(self, url: str) -> dict:
        return self.data.setdefault('servers', {}).setdefault(server_url(url), {})

    def save(self, url: str, context: Context | None = None, jobs: list[Job] | None = None) -> None:
        """Remember url, optional session IDs, and optional job IDs; never store input or keys."""
        self.data['api_url'] = server_url(url)
        entry = self.entry(url)
        if context is not None:
            for name in ('conversation_id', 'capture_id'):
                if getattr(context, name):
                    entry[name] = str(getattr(context, name))
        if jobs is not None:
            entry['jobs'] = [{'id': str(job.id), 'kind': job.kind, 'target': str(job.target) if job.target else None, 'status': job.status} for job in jobs]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.cli-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.data, stream, indent=2)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def resume(self, url: str) -> Context:
        entry = self.entry(url)
        try:
            return Context(**{name: UUID(entry[name]) for name in ('conversation_id', 'capture_id') if entry.get(name)})
        except (ValueError, TypeError) as error:
            raise ClientError('Saved conversation IDs are invalid. Choose a fresh CLI state file.') from error

    def jobs(self, url: str) -> list[Job]:
        try:
            return [Job(UUID(row['id']), row['kind'], UUID(row['target']) if row.get('target') else None, row.get('status', 'pending')) for row in self.entry(url).get('jobs', [])]
        except (ValueError, TypeError, KeyError) as error:
            raise ClientError('Saved job IDs are invalid. Choose a fresh CLI state file.') from error
