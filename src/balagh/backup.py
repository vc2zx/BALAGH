"""Encrypted SQLite and upload backup; restore only into an empty directory."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from balagh import database


MAGIC = b"BALAGHENC1"


def _key(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 16:
        raise ValueError("Backup passphrase must be at least 16 characters")
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2**15, r=8, p=1,
                          dklen=32, maxmem=64 * 1024 * 1024)


def make_backup(output: Path, passphrase: str) -> None:
    if output.exists():
        raise FileExistsError(output)
    database.init_db()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        snapshot = root / "balagh.db"
        with database._connection() as source, closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                                        "schema_version": 3}), encoding="utf-8")
        archive = root / "payload.tar"
        with tarfile.open(archive, "w") as tar:
            tar.add(snapshot, arcname="balagh.db")
            tar.add(manifest, arcname="manifest.json")
            uploads = database.DATA_DIR / "uploads"
            if uploads.is_dir():
                for path in uploads.iterdir():
                    if path.is_file() and path.name != ".gitkeep":
                        tar.add(path, arcname=f"uploads/{path.name}")
        salt, nonce = os.urandom(16), os.urandom(12)
        encryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce)).encryptor()
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with archive.open("rb") as source, output.open("xb") as destination:
                destination.write(MAGIC + salt + nonce)
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    destination.write(encryptor.update(chunk))
                destination.write(encryptor.finalize())
                destination.write(encryptor.tag)
        except Exception:
            output.unlink(missing_ok=True)
            raise


def restore_backup(source_path: Path, target_dir: Path, passphrase: str) -> None:
    if target_dir.exists() and any(target_dir.iterdir()):
        raise ValueError("Restore target must be an empty directory")
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "payload.tar"
        with source_path.open("rb") as source:
            header = source.read(len(MAGIC) + 16 + 12)
            if not header.startswith(MAGIC) or len(header) != len(MAGIC) + 28:
                raise ValueError("Invalid BALAGH backup header")
            salt = header[len(MAGIC):len(MAGIC) + 16]
            nonce = header[-12:]
            source.seek(0, 2)
            end = source.tell()
            source.seek(end - 16)
            tag = source.read(16)
            source.seek(len(header))
            decryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce, tag)).decryptor()
            remaining = end - 16 - len(header)
            with archive.open("wb") as destination:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Truncated backup")
                    destination.write(decryptor.update(chunk))
                    remaining -= len(chunk)
                destination.write(decryptor.finalize())
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            for member in members:
                path = Path(member.name)
                if not member.isfile() or (member.name not in {"balagh.db", "manifest.json"}
                                           and not (len(path.parts) == 2 and path.parts[0] == "uploads")):
                    raise ValueError("Unexpected backup member")
            if "balagh.db" not in {m.name for m in members}:
                raise ValueError("Backup has no database")
            target_dir.mkdir(parents=True, exist_ok=True)
            for member in members:
                destination = target_dir / member.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as input_file, destination.open("xb") as output_file:
                    for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                        output_file.write(chunk)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--output", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--input", type=Path, required=True)
    restore.add_argument("--target-dir", type=Path, required=True)
    args = parser.parse_args()
    passphrase = getpass.getpass("Backup passphrase: ")
    if args.command == "create":
        make_backup(args.output, passphrase)
        print(f"Encrypted backup: {args.output}")
    else:
        restore_backup(args.input, args.target_dir, passphrase)
        print(f"Restored into: {args.target_dir}")


if __name__ == "__main__":
    main()
