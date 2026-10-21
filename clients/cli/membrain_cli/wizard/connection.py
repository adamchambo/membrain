"""Select the address of an already running local server."""
from ..config import server_url
from ..types import ClientError


def choose(default: str, read=input, write=print) -> str:
    """Prompt using default URL; read/write provide injectable terminal IO."""
    while True:
        raw = read(f'Local API URL [{default}]: ').strip()
        if raw in ('/quit', '/back'):
            raise EOFError
        try:
            return server_url(raw or default)
        except ClientError as error:
            write(str(error))
