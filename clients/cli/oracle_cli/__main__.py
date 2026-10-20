"""Run the local navigation prototype with python -m oracle_cli."""
from .session import Session
from .stub_api import StubAPI


def main() -> None:
    """Start the menu loop with a local, in-memory stub backend."""
    Session(StubAPI()).run()


if __name__ == "__main__":
    main()
