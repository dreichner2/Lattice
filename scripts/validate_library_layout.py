#!/usr/bin/env python3
"""Validate the clone-ready CS Library and Syncthing directory contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_FILE = "library-layout.json"


def _relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip() or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or candidate.as_posix() != value:
        return None
    if any(part in {"", ".", ".."} for part in candidate.parts):
        return None
    return value


def _path_list(data: dict[str, Any], key: str, errors: list[str]) -> list[str]:
    raw = data.get(key)
    if not isinstance(raw, list) or not raw:
        errors.append(f"{key} must be a non-empty array")
        return []

    values: list[str] = []
    for item in raw:
        value = _relative_path(item)
        if value is None:
            errors.append(f"{key} contains an unsafe or non-canonical path: {item!r}")
        else:
            values.append(value)
    if len(values) != len(set(values)):
        errors.append(f"{key} contains duplicate paths")
    return values


def load_layout(root: Path = ROOT) -> dict[str, Any]:
    path = root / LAYOUT_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{LAYOUT_FILE} must contain a JSON object")
    return payload


def validate_layout(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    try:
        layout = load_layout(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"cannot load {LAYOUT_FILE}: {error}"]

    if layout.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    content_directories = _path_list(layout, "content_directories", errors)
    required_root_entries = _path_list(layout, "required_root_entries", errors)

    syncthing = layout.get("syncthing")
    if not isinstance(syncthing, dict):
        errors.append("syncthing must be an object")
        shared_paths: list[str] = []
    else:
        for key in ("folder_id", "folder_label", "folder_type"):
            if not isinstance(syncthing.get(key), str) or not syncthing[key].strip():
                errors.append(f"syncthing.{key} must be a non-empty string")
        shared_paths = _path_list(syncthing, "shared_paths", errors)

    for relative in content_directories:
        directory = root / relative
        if not directory.is_dir():
            errors.append(f"missing content directory: {relative}")
        if not (directory / ".gitkeep").is_file():
            errors.append(f"missing clone placeholder: {relative}/.gitkeep")

    for relative in required_root_entries:
        if not (root / relative).exists():
            errors.append(f"missing required root entry: {relative}")

    ignore_path = root / ".stignore"
    try:
        patterns = [
            line.strip()
            for line in ignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("//")
        ]
    except OSError as error:
        errors.append(f"cannot load .stignore: {error}")
        patterns = []

    for relative in shared_paths:
        root_pattern = f"!/{relative}"
        if root_pattern not in patterns:
            errors.append(f".stignore does not include {relative}")
        if (root / relative).is_dir() and f"!/{relative}/**" not in patterns:
            errors.append(f".stignore does not include descendants of {relative}")
    if patterns and patterns[-1] != "*":
        errors.append(".stignore must end with the catch-all '*' rule")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="CS Library root to validate (default: repository root)",
    )
    args = parser.parse_args()
    errors = validate_layout(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    layout = load_layout(args.root.resolve())
    print(
        "CS Library layout OK: "
        f"{len(layout['content_directories'])} content directories; "
        f"Syncthing folder {layout['syncthing']['folder_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
