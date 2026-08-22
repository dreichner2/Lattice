#!/usr/bin/env python3
"""Sign exact update-manifest bytes with the offline Lattice release key."""

from __future__ import annotations

import argparse
import hashlib
import os
import stat
import subprocess
import tempfile
from pathlib import Path


PRODUCTION_PUBLIC_KEY_SHA256 = (
    "d83bee18c8410be46d7dccac3784ec0ecc1fdd516fa5b27b0de1fe15580348bf"
)
MAXIMUM_MANIFEST_SIZE = 64 * 1024
RSA_3072_SIGNATURE_SIZE = 384


def run_openssl(arguments: list[str], *, stdin: bytes | None = None) -> bytes:
    try:
        completed = subprocess.run(
            ["openssl", *arguments],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as error:
        raise RuntimeError("OpenSSL is required to sign a Lattice release") from error
    if completed.returncode != 0:
        # Do not surface OpenSSL stderr: it may include sensitive key-provider
        # diagnostics. A concise failure is enough for the release operator.
        raise RuntimeError("OpenSSL could not use the configured release signing key")
    return completed.stdout


def verify_private_key_identity(private_key: Path) -> bytes:
    if not private_key.is_file():
        raise ValueError("the release signing key path is not a regular file")
    if os.name == "posix":
        mode = stat.S_IMODE(private_key.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError("the release signing key must not be accessible to group or other users")

    public_der = run_openssl(
        ["pkey", "-in", os.fspath(private_key), "-pubout", "-outform", "DER"]
    )
    fingerprint = hashlib.sha256(public_der).hexdigest()
    if fingerprint != PRODUCTION_PUBLIC_KEY_SHA256:
        raise ValueError("the configured release key does not match the production public key fingerprint")
    return public_der


def sign_manifest(manifest: Path, private_key: Path, output: Path) -> None:
    manifest = manifest.resolve()
    private_key = private_key.resolve()
    output = output.resolve()
    if manifest in {private_key, output} or private_key == output:
        raise ValueError("manifest, private key, and signature paths must be distinct")
    if not manifest.is_file():
        raise ValueError("update manifest does not exist")
    size = manifest.stat().st_size
    if size <= 0 or size > MAXIMUM_MANIFEST_SIZE:
        raise ValueError("update manifest has an unsafe size")

    public_der = verify_private_key_identity(private_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lattice-sign-") as temporary:
        temporary_root = Path(temporary)
        signature_path = temporary_root / "manifest.sig"
        public_pem_path = temporary_root / "release-public.pem"
        public_pem = run_openssl(
            ["pkey", "-pubin", "-inform", "DER", "-pubout", "-outform", "PEM"],
            stdin=public_der,
        )
        public_pem_path.write_bytes(public_pem)
        run_openssl(
            [
                "dgst",
                "-sha256",
                "-sign",
                os.fspath(private_key),
                "-out",
                os.fspath(signature_path),
                os.fspath(manifest),
            ]
        )
        signature = signature_path.read_bytes()
        if len(signature) != RSA_3072_SIGNATURE_SIZE:
            raise ValueError("release key did not produce an RSA-3072 signature")
        run_openssl(
            [
                "dgst",
                "-sha256",
                "-verify",
                os.fspath(public_pem_path),
                "-signature",
                os.fspath(signature_path),
                os.fspath(manifest),
            ]
        )
        temporary_output = output.with_name(f".{output.name}.{os.getpid()}.tmp")
        try:
            temporary_output.write_bytes(signature)
            os.replace(temporary_output, output)
        finally:
            temporary_output.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    sign_manifest(args.manifest, args.private_key, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
