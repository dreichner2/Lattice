#!/usr/bin/env python3
"""Build stable, version-pinned Lattice desktop update metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
REPOSITORY = "dreichner2/Lattice"
WINDOWS_PLATFORM = "windows-x64"
MACOS_ARM64_PLATFORM = "macos-arm64"
WINDOWS_ASSET_NAME = "Lattice-Windows-win-x64.zip"
MACOS_ASSET_NAME = "Lattice-macOS.zip"
# Backward-compatible import used by existing release tests and tooling.
ASSET_NAME = WINDOWS_ASSET_NAME
MAXIMUM_ASSET_SIZE = 1_073_741_824


@dataclass(frozen=True)
class AssetInput:
    platform: str
    path: Path


def stable_version(value: str) -> str:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        raise ValueError("version must be stable major.minor.patch SemVer")
    for part in match.groups():
        if int(part) > 2_147_483_647:
            raise ValueError("version component exceeds the supported numeric range")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    version: str,
    archive: Path,
    macos_archive: Path | None = None,
    published_at: str,
    repository: str = REPOSITORY,
) -> dict[str, object]:
    version = stable_version(version)
    if repository != REPOSITORY:
        raise ValueError(f"repository must be exactly {REPOSITORY}")
    if not UTC_TIMESTAMP_RE.fullmatch(published_at):
        raise ValueError("published_at must use whole-second UTC ISO-8601 form")
    try:
        timestamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("published_at must be an ISO-8601 timestamp") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
        raise ValueError("published_at must be UTC")

    tag = f"v{version}"
    archives = [
        AssetInput(WINDOWS_PLATFORM, archive.resolve()),
    ]
    if macos_archive is not None:
        archives.append(AssetInput(MACOS_ARM64_PLATFORM, macos_archive.resolve()))

    expected_names = {
        WINDOWS_PLATFORM: WINDOWS_ASSET_NAME,
        MACOS_ARM64_PLATFORM: MACOS_ASSET_NAME,
    }
    assets: dict[str, dict[str, object]] = {}
    for candidate in archives:
        expected_name = expected_names[candidate.platform]
        if not candidate.path.is_file() or candidate.path.name != expected_name:
            raise ValueError(
                f"{candidate.platform} archive must be an existing file named {expected_name}"
            )
        size = candidate.path.stat().st_size
        if size <= 0 or size > MAXIMUM_ASSET_SIZE:
            raise ValueError(f"{candidate.platform} archive size is outside the updater safety limit")
        assets[candidate.platform] = {
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{tag}/{expected_name}"
            ),
            "sha256": sha256_file(candidate.path),
            "size": size,
        }

    return {
        "schemaVersion": 2,
        "repository": repository,
        "releaseVersion": version,
        "releaseTag": tag,
        "publishedAt": published_at,
        "assets": assets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--macos-archive", type=Path, required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = build_manifest(
        version=args.version,
        archive=args.archive,
        macos_archive=args.macos_archive,
        published_at=args.published_at,
        repository=args.repository,
    )
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ValueError("generated manifest exceeds the application safety limit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
