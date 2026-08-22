#!/usr/bin/env python3
"""Validate the clone-ready Lattice and Syncthing directory contract."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAYOUT_FILE = "library-layout.json"
TAXONOMY_FILE = "library-taxonomy.json"
SUBJECT_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_ASSIGNED_SUBJECTS = 64


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


def load_taxonomy(root: Path = ROOT) -> dict[str, Any]:
    path = root / TAXONOMY_FILE
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{TAXONOMY_FILE} must contain a JSON object")
    return payload


def _validate_taxonomy(root: Path, errors: list[str]) -> None:
    try:
        taxonomy = load_taxonomy(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(f"cannot load {TAXONOMY_FILE}: {error}")
        return

    if (
        type(taxonomy.get("schema_version")) is not int
        or taxonomy.get("schema_version") != 1
    ):
        errors.append(f"{TAXONOMY_FILE} schema_version must be 1")

    raw_subjects = taxonomy.get("subjects")
    if not isinstance(raw_subjects, list) or not raw_subjects:
        errors.append(f"{TAXONOMY_FILE} subjects must be a non-empty array")
        subject_ids: set[str] = set()
    else:
        if len(raw_subjects) > MAX_ASSIGNED_SUBJECTS:
            errors.append(
                f"{TAXONOMY_FILE} subjects must not exceed "
                f"{MAX_ASSIGNED_SUBJECTS} entries"
            )
        subject_ids = set()
        for index, subject in enumerate(raw_subjects):
            if not isinstance(subject, dict):
                errors.append(f"{TAXONOMY_FILE} subjects[{index}] must be an object")
                continue
            subject_id = subject.get("id")
            if not isinstance(subject_id, str) or not SUBJECT_ID_PATTERN.fullmatch(subject_id):
                errors.append(
                    f"{TAXONOMY_FILE} subjects[{index}].id must be a lowercase kebab-case ID"
                )
            elif subject_id in subject_ids:
                errors.append(f"{TAXONOMY_FILE} contains duplicate subject ID: {subject_id}")
            else:
                subject_ids.add(subject_id)
            for key in ("name", "description"):
                value = subject.get(key)
                if not isinstance(value, str) or not value.strip():
                    errors.append(
                        f"{TAXONOMY_FILE} subjects[{index}].{key} must be a non-empty string"
                    )

    for key in ("default_import_subject_id", "catalog_default_subject_id"):
        value = taxonomy.get(key)
        if not isinstance(value, str) or value not in subject_ids:
            errors.append(f"{TAXONOMY_FILE} {key} must reference a defined subject")

    for key in ("topic_defaults", "work_assignments"):
        mapping = taxonomy.get(key)
        if not isinstance(mapping, dict):
            errors.append(f"{TAXONOMY_FILE} {key} must be an object")
            continue
        for source_id, assignment in mapping.items():
            if (
                not isinstance(source_id, str)
                or not source_id
                or source_id != source_id.strip()
            ):
                errors.append(f"{TAXONOMY_FILE} {key} contains an invalid key")
            assigned_subjects = [assignment] if isinstance(assignment, str) else assignment
            if (
                not isinstance(assigned_subjects, list)
                or not assigned_subjects
                or len(assigned_subjects) > len(subject_ids)
                or any(
                    not isinstance(subject_id, str) or subject_id not in subject_ids
                    for subject_id in assigned_subjects
                )
                or len(set(assigned_subjects)) != len(assigned_subjects)
            ):
                errors.append(
                    f"{TAXONOMY_FILE} {key}.{source_id} must reference one or more "
                    "unique defined subjects"
                )


def validate_layout(root: Path = ROOT) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    try:
        layout = load_layout(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"cannot load {LAYOUT_FILE}: {error}"]

    if (
        type(layout.get("schema_version")) is not int
        or layout.get("schema_version") != 1
    ):
        errors.append("schema_version must be 1")

    content_directories = _path_list(layout, "content_directories", errors)
    required_root_entries = _path_list(layout, "required_root_entries", errors)

    sidecars = layout.get("sidecars")
    if not isinstance(sidecars, dict):
        errors.append("sidecars must be an object")
    else:
        if sidecars.get("suffix") != ".library.json":
            errors.append("sidecars.suffix must be '.library.json'")
        if sidecars.get("append_to_full_filename") is not True:
            errors.append("sidecars.append_to_full_filename must be true")
        if sidecars.get("location") != "adjacent":
            errors.append("sidecars.location must be 'adjacent'")
        if sidecars.get("shared_via_syncthing") is not True:
            errors.append("sidecars.shared_via_syncthing must be true")

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

    _validate_taxonomy(root, errors)

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
    for required_ignore in ("(?d).gitkeep", "(?d).syncthing.*.tmp", "/lectures/catalog.json"):
        if required_ignore not in patterns:
            errors.append(f".stignore must exclude Git-owned or temporary path: {required_ignore}")
    if patterns and patterns[-1] != "*":
        errors.append(".stignore must end with the catch-all '*' rule")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Lattice root to validate (default: repository root)",
    )
    args = parser.parse_args()
    errors = validate_layout(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    layout = load_layout(args.root.resolve())
    print(
        "Lattice layout OK: "
        f"{len(layout['content_directories'])} content directories; "
        f"Syncthing folder {layout['syncthing']['folder_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
