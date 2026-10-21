"""Membrain terminal client: local API by default, explicit --stub navigation mode."""
import argparse
from .config import Store
from .session import Session
from .types import ClientError


def main(argv=None):
    """Parse argv (or process arguments) and start setup or the interactive session."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['menu', 'setup'], nargs='?', default='menu')
    parser.add_argument('--api-url', help='Local server address; overrides saved settings and MEMBRAIN_API_URL')
    parser.add_argument('--stub', action='store_true', help='Run local demo responses without API calls or saved state')
    parser.add_argument('--no-setup', action='store_true', help='Skip automatic setup; use current server settings')
    args = parser.parse_args(argv)
    if args.stub:
        from .stub_api import StubAPI
        Session(StubAPI()).run()
        return 0
    try:
        from .api import SDKBackend
        from .wizard.connection import choose
        from .wizard.flow import run as wizard
        store = Store()
        url = args.api_url or store.api_url
        if args.command == 'setup':
            url = choose(url)
        backend = SDKBackend(url, jobs=store.jobs(url))
        try:
            if args.command == 'setup':
                if wizard(backend):
                    store.save(url)
                return 0
            report = backend.readiness()
            if not args.no_setup and (not store.path.exists() or not report.database.ready):
                wizard(backend)
            store.save(url)
            Session(backend, store=store, api_url=url, context=store.resume(url), setup=lambda: wizard(backend)).run()
        finally:
            backend.close()
    except (EOFError, KeyboardInterrupt):
        return 0
    except ImportError:
        print('Install the local packages with the project Python: .venv/bin/python -m pip install -e sdk/python -e clients/cli')
        return 1
    except (ClientError, OSError) as error:
        print(str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
