#!/usr/bin/env python3
"""PyInstaller entry point for the Windows Lattice local server."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cross_platform_server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
