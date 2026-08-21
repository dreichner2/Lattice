#!/bin/zsh

set -e
library_root=${0:A:h}
cd "$library_root"
exec /usr/bin/env python3 scripts/library_ui.py
