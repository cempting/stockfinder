"""Verified backup and safe restore for persistent Stockfinder data."""

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, mkdtemp
from uuid import uuid4
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from stockfinder.runtime import application_data_dir

MANIFEST_NAME = "manifest.json"
BACKUP_VERSION = 1


def create_backup(source: str | Path, destination: str | Path) -> Path:
    """Create an atomic ZIP archive with checksums for every persistent file."""
    source_path = Path(source).resolve()
    destination_path = Path(destination).resolve()
    if not source_path.is_dir():
        raise ValueError(f"Backup source is not a directory: {source_path}")
    if source_path == destination_path or source_path in destination_path.parents:
        raise ValueError("Backup destination must be outside the data directory")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination_path.with_name(
        f".{destination_path.name}.{uuid4().hex}.tmp"
    )
    files = {}
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(source_path.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                relative = path.relative_to(source_path).as_posix()
                payload = _consistent_payload(path)
                archive.writestr(f"data/{relative}", payload)
                files[relative] = {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            manifest = {
                "version": BACKUP_VERSION,
                "created_at": datetime.now(UTC).isoformat(),
                "files": files,
            }
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            )
        temporary.replace(destination_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination_path


def verify_backup(archive_path: str | Path) -> dict:
    """Validate archive structure, manifest, sizes, and SHA-256 checksums."""
    path = Path(archive_path)
    try:
        with ZipFile(path) as archive:
            names = archive.namelist()
            if MANIFEST_NAME not in names:
                raise ValueError("Backup manifest is missing")
            manifest = json.loads(archive.read(MANIFEST_NAME))
            if manifest.get("version") != BACKUP_VERSION:
                raise ValueError("Unsupported backup version")
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise ValueError("Backup manifest files must be an object")
            expected_names = {MANIFEST_NAME}
            for relative, evidence in files.items():
                _validate_relative_path(relative)
                archive_name = f"data/{relative}"
                expected_names.add(archive_name)
                payload = archive.read(archive_name)
                if len(payload) != evidence.get("size"):
                    raise ValueError(f"Backup size mismatch: {relative}")
                digest = hashlib.sha256(payload).hexdigest()
                if digest != evidence.get("sha256"):
                    raise ValueError(f"Backup checksum mismatch: {relative}")
            if set(names) != expected_names:
                raise ValueError("Backup contains untracked or unsafe files")
            return manifest
    except (BadZipFile, KeyError, json.JSONDecodeError, OSError) as error:
        raise ValueError(f"Invalid backup archive: {error}") from error


def restore_backup(archive_path: str | Path, target: str | Path) -> Path:
    """Restore a verified archive only into a new or empty directory."""
    manifest = verify_backup(archive_path)
    target_path = Path(target).resolve()
    if target_path.exists() and any(target_path.iterdir()):
        raise ValueError("Restore target must be new or empty")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(mkdtemp(prefix=".stockfinder-restore-", dir=target_path.parent))
    staged_data = staging_root / "data"
    try:
        staged_data.mkdir()
        with ZipFile(archive_path) as archive:
            for relative in manifest["files"]:
                destination = staged_data / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(f"data/{relative}"))
        if target_path.exists():
            target_path.rmdir()
        staged_data.replace(target_path)
    finally:
        if staging_root.exists():
            for path in sorted(
                staging_root.rglob("*"), key=lambda item: len(item.parts), reverse=True
            ):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging_root.rmdir()
    return target_path


def prune_backups(
    directory: str | Path,
    keep: int,
    *,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    """Remove older managed archives while leaving unrelated files untouched."""
    if keep < 1:
        raise ValueError("Backup retention must keep at least one archive")
    directory_path = Path(directory)
    if not directory_path.is_dir():
        raise ValueError(f"Backup directory does not exist: {directory_path}")
    archives = sorted(
        directory_path.glob("stockfinder-*.zip"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    removed = tuple(
        sorted(archives[keep:], key=lambda path: (path.stat().st_mtime, path.name))
    )
    if not dry_run:
        for path in removed:
            path.unlink()
    return removed


def _validate_relative_path(relative: str) -> None:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"Unsafe backup path: {relative}")


def _consistent_payload(path: Path) -> bytes:
    if path.suffix.lower() != ".db":
        return path.read_bytes()
    with TemporaryDirectory() as temporary_directory:
        snapshot_path = Path(temporary_directory) / path.name
        with (
            closing(sqlite3.connect(path)) as source,
            closing(sqlite3.connect(snapshot_path)) as destination,
        ):
            source.backup(destination)
        return snapshot_path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    """Create, verify, or restore a Stockfinder data backup."""
    parser = argparse.ArgumentParser(description="Manage Stockfinder data backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="Create a verified backup")
    create_parser.add_argument("archive", type=Path)
    verify_parser = subparsers.add_parser("verify", help="Verify a backup")
    verify_parser.add_argument("archive", type=Path)
    restore_parser = subparsers.add_parser(
        "restore", help="Restore into a new or empty directory"
    )
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("target", type=Path)
    prune_parser = subparsers.add_parser(
        "prune", help="Remove old managed backup archives"
    )
    prune_parser.add_argument("directory", type=Path)
    prune_parser.add_argument("--keep", type=int, default=14)
    prune_parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "create":
            path = create_backup(application_data_dir(), arguments.archive)
            print(f"Backup created: {path}")
        elif arguments.command == "verify":
            manifest = verify_backup(arguments.archive)
            print(f"Backup verified: {len(manifest['files'])} files")
        elif arguments.command == "restore":
            path = restore_backup(arguments.archive, arguments.target)
            print(f"Backup restored: {path}")
        else:
            removed = prune_backups(
                arguments.directory,
                arguments.keep,
                dry_run=arguments.dry_run,
            )
            action = "Would remove" if arguments.dry_run else "Removed"
            print(f"{action} {len(removed)} backup(s)")
            for path in removed:
                print(path)
    except ValueError as error:
        print(f"Backup operation failed: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())