"""Bootstrap settings readable before a database exists; environment overrides file."""

import json
import os
import tempfile
import fcntl
from contextlib import contextmanager
from pathlib import Path

from app.errors import NotConfigured


def config_path() -> Path:
    return Path((os.getenv("MEMBRAIN_CONFIG_FILE") or os.getenv("ORACLE_CONFIG_FILE") or str(Path(__file__).resolve().parents[2] / ".local" / "config.json")))


def read_config() -> dict:
    try:
        value = json.loads(config_path().read_text())
        if not isinstance(value, dict):
            raise ValueError("Settings must be an object")
        return value
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise NotConfigured("The local configuration file could not be read") from exc


def environment_value(name: str, *, allow_empty: bool = False):
    """Read name or its legacy ORACLE alias; allow_empty preserves empty task prefixes."""
    canonical = name.replace("ORACLE_", "MEMBRAIN_", 1) if name.startswith("ORACLE_") else name
    legacy = canonical.replace("MEMBRAIN_", "ORACLE_", 1) if canonical.startswith("MEMBRAIN_") else canonical
    for key in dict.fromkeys((canonical, legacy)):
        value = os.getenv(key)
        if value is not None and (value or allow_empty):
            return value
    return None


def setting(name: str, default=None, *, allow_empty: bool = False):
    """Resolve name with environment priority, legacy aliases and an optional empty-value policy."""
    value = environment_value(name, allow_empty=allow_empty)
    if value is not None:
        return value
    settings = read_config().get("settings", {})
    canonical = name.replace("ORACLE_", "MEMBRAIN_", 1) if name.startswith("ORACLE_") else name
    legacy = canonical.replace("MEMBRAIN_", "ORACLE_", 1) if canonical.startswith("MEMBRAIN_") else canonical
    return settings.get(canonical, settings.get(legacy, default))


def write_config(value: dict) -> None:
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".membrain-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w") as file:
            json.dump(value, file, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def config_lock():
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target.with_suffix(".lock"), "a") as lock:
        os.chmod(target.with_suffix(".lock"), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def remember_embedding_connection(key: str, url: str, api_key: str | None) -> None:
    with config_lock():
        value = read_config()
        value.setdefault("embedding_connections", {})[key] = {"url": url, "api_key": api_key}
        write_config(value)
