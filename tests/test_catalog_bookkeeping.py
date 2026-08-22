from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch  # noqa: E402


HELD_ARRIVAL_IDS = {
    "url:00295b82ff725c52a71351a0bb1ee1bdb1584e594a62395d3fb382aefd0f4d42",
    "url:b3129f44c4a26b534176bb0f83d85e1ed26a6cdf93ebebacb20104eab2d6bc00",
    "url:5d633e4514799a123616c565beeaa498d9900f615969273b320a969fb0c336a0",
    "url:89bfbed17259573dcdc1c1f0e14347030aa42902baba7e0a395fcd7493594aac",
    "url:fa522a14f9b1631232ff6b34bc092686803b71cc8154cbf31c7ac523a75108dc",
    "url:41baea09d066e0167ca0943968d44f7f07790be700440427f78c034910e5765d",
    "url:cd514fbdf07b1f96f9b32304c4bff62e9c1f048626439c9dd2c881bc09549801",
    "url:389dfabdfa94bd21bb3ccebc5074a84c4faa0661c885ca3b3cbe70186f47a747",
    "url:0c550af6f81215e1b4909f4e8e99e44c7bb18967835c0dbd559191a65d01a275",
    "url:40807dab08eb08477d6bd1ed22b91b4dcd6633550a4a62682ecbbd00c00d8b08",
    "url:5de3d24deb279f5bc7669a90742876d2807200eabc9195bb6e8714b400b0532a",
    "url:8ab9d339a2c2781382e6aa4c3c472a94edfcc05d10e3eedf63cbaac9530e9932",
    "url:d9d788538f999a0320da8f115edc3d4cf8f39aacbd6d8fe0ed9fedf82b395647",
}


def add_tracked_payload(root: Path, relative: str, payload: bytes) -> str:
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    record_path = root / "metadata" / Path(relative).with_suffix(".json")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(
            {
                "title": destination.stem,
                "path": relative,
                "bytes": len(payload),
                "sha256": digest,
            }
        ),
        encoding="utf-8",
    )
    return digest


class CatalogBookkeepingTests(unittest.TestCase):
    def test_repository_catalog_has_only_unique_detail_records(self) -> None:
        catalog = (ROOT / "CATALOG.md").read_text(encoding="utf-8")
        self.assertIn(
            "> **96 readable works · 125 readable artifacts · 0 exact duplicates**",
            catalog,
        )
        table_markers = [
            line for line in catalog.splitlines() if line.startswith("|") and "<!-- work:" in line
        ]
        detail_ids = set(
            re.findall(r"^<!-- work: ([^>]+) -->$", catalog, flags=re.MULTILINE)
        )
        self.assertEqual(len(table_markers), 83)
        self.assertEqual(
            detail_ids,
            {"book:nand2tetris-projects", *HELD_ARRIVAL_IDS},
        )
        self.assertEqual(fetch.catalog_readable_work_count(catalog), 96)
        self.assertNotIn("<!-- work: arxiv:1706.03762v7 -->", catalog)
        self.assertNotIn("](papers/attention.pdf)", catalog)
        self.assertIn(
            "[Reflections on Trusting Trust](papers/reflections-on-trusting-trust.pdf)",
            catalog,
        )
        self.assertIn(
            "- Local path: `papers/reflections-on-trusting-trust.pdf`",
            catalog,
        )
        self.assertIn(
            "[Scaling Memcache at Facebook](papers/scaling-memcache-at-facebook.pdf)",
            catalog,
        )
        self.assertIn(
            "- Local path: `papers/scaling-memcache-at-facebook.pdf`",
            catalog,
        )

    def test_semantic_work_count_deduplicates_legacy_representations(self) -> None:
        catalog = """
| <!-- work: current --> [Same Work](papers/current-name.pdf) |

<!-- work: legacy -->
### [Same Work](papers/obsolete-name.pdf)

<!-- work: archive -->
### [Course Software](books/course-software.zip)
"""
        self.assertEqual(fetch.catalog_readable_work_count(catalog), 1)

    def test_audit_uses_tracked_inventory_and_excludes_private_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            tracked_digest = add_tracked_payload(root, "books/tracked.pdf", b"tracked")
            archive_digest = add_tracked_payload(
                root, "books/nand2tetris-projects.zip", b"course-suite"
            )

            private = root / "books" / "Private Import.pdf"
            private.write_bytes(b"tracked")
            private.with_name(private.name + fetch.SYNCED_SIDECAR_SUFFIX).write_text(
                json.dumps(
                    {
                        "title": "Private Import",
                        "path": "books/Private Import.pdf",
                        "bytes": len(b"tracked"),
                        "sha256": tracked_digest,
                    }
                ),
                encoding="utf-8",
            )

            catalog = """
| <!-- work: tracked --> [Tracked](books/tracked.pdf) |

<!-- work: archive -->
### [Nand2Tetris Suite](books/nand2tetris-projects.zip)
"""
            (root / "CATALOG.md").write_text(catalog, encoding="utf-8")
            manifest = root / "manifests" / "library.sha256"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                "".join(
                    [
                        f"{archive_digest}  books/nand2tetris-projects.zip\n",
                        f"{tracked_digest}  books/tracked.pdf\n",
                    ]
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with mock.patch.object(fetch, "REPO_ROOT", root), contextlib.redirect_stdout(output):
                result = fetch.cmd_audit(None)

        self.assertEqual(result, 0, output.getvalue())
        self.assertIn(
            "1 readable works, 1 readable artifacts, 2 canonical records, "
            "0 exact duplicates",
            output.getvalue(),
        )

    def test_manifest_includes_tracked_archive_but_not_private_import(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            tracked_digest = add_tracked_payload(root, "books/tracked.pdf", b"tracked")
            archive_digest = add_tracked_payload(
                root, "books/nand2tetris-projects.zip", b"course-suite"
            )
            private = root / "books" / "private.pdf"
            private.write_bytes(b"private")
            private.with_name(private.name + fetch.SYNCED_SIDECAR_SUFFIX).write_text(
                "{}", encoding="utf-8"
            )

            with mock.patch.object(fetch, "REPO_ROOT", root), contextlib.redirect_stdout(
                io.StringIO()
            ):
                result = fetch.cmd_manifest(None)
            lines = (root / "manifests" / "library.sha256").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(result, 0)
        self.assertEqual(
            lines,
            [
                f"{archive_digest}  books/nand2tetris-projects.zip",
                f"{tracked_digest}  books/tracked.pdf",
            ],
        )


if __name__ == "__main__":
    unittest.main()
