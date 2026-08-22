#!/usr/bin/env python3
"""Build the signed-build metadata consumed by both desktop updaters."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PLATFORM_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class AssetInput:
    platform: str
    path: Path


def parse_asset(value: str) -> AssetInput:
    platform, separator, raw_path = value.partition("=")
    if not separator or not PLATFORM_RE.fullmatch(platform):
        raise argparse.ArgumentTypeError("assets must use platform=/path/to/archive")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"asset does not exist: {path}")
    return AssetInput(platform=platform, path=path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    commit: str,
    repository: str,
    tag: str,
    channel: str,
    assets: list[AssetInput],
    published_at: str | None = None,
) -> dict[str, object]:
    commit = commit.lower()
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("commit must be a full 40-character lowercase Git SHA")
    if not REPOSITORY_RE.fullmatch(repository):
        raise ValueError("repository must use owner/name")
    if not tag or "/" in tag or tag in {".", ".."}:
        raise ValueError("tag must be a single safe GitHub release tag")
    if channel != "main":
        raise ValueError("the desktop updater currently supports only the main channel")
    if not assets:
        raise ValueError("at least one release asset is required")
    platforms = [asset.platform for asset in assets]
    if len(platforms) != len(set(platforms)):
        raise ValueError("each platform may appear only once")

    timestamp = published_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("published_at must be an ISO-8601 timestamp") from error
    if parsed_timestamp.tzinfo is None:
        raise ValueError("published_at must include a timezone")

    encoded_tag = quote(tag, safe="")
    release_root = f"https://github.com/{repository}/releases/download/{encoded_tag}"
    manifest_assets: dict[str, object] = {}
    for asset in sorted(assets, key=lambda item: item.platform):
        manifest_assets[asset.platform] = {
            "url": f"{release_root}/{quote(asset.path.name, safe='')}",
            "sha256": sha256_file(asset.path),
            "size": asset.path.stat().st_size,
        }

    return {
        "schemaVersion": 1,
        "repository": repository,
        "channel": channel,
        "commit": commit,
        "publishedAt": timestamp,
        "assets": manifest_assets,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", default="latest-main")
    parser.add_argument("--channel", default="main")
    parser.add_argument("--published-at")
    parser.add_argument("--asset", action="append", type=parse_asset, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    manifest = build_manifest(
        commit=args.commit,
        repository=args.repository,
        tag=args.tag,
        channel=args.channel,
        assets=args.asset,
        published_at=args.published_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
