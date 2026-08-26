#!/usr/bin/env python3
"""PyInstaller entry point for the Windows Lattice local server."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def bootstrap(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--study-kernel"]:
        # PyInstaller's executable is also the only available Python runtime in
        # the self-contained Windows package. This exact mode exposes only the
        # newline-delimited kernel bridge on inherited stdio.
        from study_kernel import serve

        serve()
        return 0

    from cross_platform_server import main

    return main(arguments)


if __name__ == "__main__":
    raise SystemExit(bootstrap())
