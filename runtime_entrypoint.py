from __future__ import annotations

import runpy
import sys
from pathlib import Path

from runtime_logging import configure_runtime_logging


def run_target(argv: list[str] | None = None) -> None:
    """Configure process logging, then execute one existing Python entrypoint.

    Railway invokes this launcher only for the long-running stream/worker services.
    The target receives its original argv unchanged apart from argv[0], exactly as if
    it had been started with `python target.py ...`.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        raise SystemExit("runtime_entrypoint.py requires a target .py file")
    target = args[0]
    if Path(target).suffix.lower() != ".py":
        raise SystemExit("runtime target must be a .py file")

    configure_runtime_logging()
    sys.argv = [target, *args[1:]]
    runpy.run_path(target, run_name="__main__")


def main() -> None:
    run_target()


if __name__ == "__main__":
    main()
