#!/usr/bin/env python3
"""
Script to sign plugin JSON files using Ed25519.
"""

import argparse
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def generate_keys(key_dir: Path):
    """Generate a new Ed25519 key pair."""
    key_dir.mkdir(parents=True, exist_ok=True)

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    # Save private key
    with open(key_dir / "plugin_signing.pem", "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # Save public key
    with open(key_dir / "plugin_signing.pub", "wb") as f:
        f.write(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    print(f"Keys generated in {key_dir}")


def sign_plugin(plugin_path: Path, private_key_path: Path):
    """Sign a plugin JSON file."""
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Type assertion for Ed25519
    if not isinstance(private_key, Ed25519PrivateKey):
        raise TypeError(f"Expected Ed25519 private key, got {type(private_key)}")

    with open(plugin_path, encoding="utf-8") as f:
        data = json.load(f)

    # Remove existing signature if any
    data.pop("signature", None)

    # Canonicalize JSON
    canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    # Sign
    signature = private_key.sign(canonical_json)
    data["signature"] = signature.hex()

    # Write back
    with open(plugin_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"Signed {plugin_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sign Spectra plugins")
    parser.add_argument("action", choices=["keygen", "sign"])
    parser.add_argument("--plugin", type=Path, help="Path to plugin JSON")
    parser.add_argument("--key-dir", type=Path, default=Path("keys"), help="Directory for keys")

    args = parser.parse_args()

    if args.action == "keygen":
        generate_keys(args.key_dir)
    elif args.action == "sign":
        if not args.plugin:
            print("Error: --plugin required for sign action")
            sys.exit(1)
        sign_plugin(args.plugin, args.key_dir / "plugin_signing.pem")
