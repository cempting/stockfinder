import hashlib
import json
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from stockfinder.backup import create_backup, main, restore_backup, verify_backup


def test_backup_round_trip_verifies_checksums_and_restores(tmp_path) -> None:
    source = tmp_path / "data"
    (source / "market").mkdir(parents=True)
    with sqlite3.connect(source / "stockfinder.db") as connection:
        connection.execute("CREATE TABLE positions (symbol TEXT)")
        connection.execute("INSERT INTO positions VALUES ('TEST')")
    (source / "market" / "SPY.parquet").write_bytes(b"market-data")
    archive = tmp_path / "backups" / "stockfinder.zip"

    create_backup(source, archive)
    manifest = verify_backup(archive)
    restored = restore_backup(archive, tmp_path / "restored")

    assert set(manifest["files"]) == {
        "market/SPY.parquet",
        "stockfinder.db",
    }
    with sqlite3.connect(restored / "stockfinder.db") as connection:
        assert connection.execute("SELECT symbol FROM positions").fetchone() == (
            "TEST",
        )
    assert (restored / "market" / "SPY.parquet").read_bytes() == b"market-data"


def test_restore_rejects_nonempty_target(tmp_path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    (source / "state.json").write_text("{}", encoding="utf-8")
    archive = create_backup(source, tmp_path / "stockfinder.zip")
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="new or empty"):
        restore_backup(archive, target)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_verify_rejects_untracked_unsafe_archive_member(tmp_path) -> None:
    archive = tmp_path / "unsafe.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
        payload = b"unsafe"
        manifest = {
            "version": 1,
            "created_at": "now",
            "files": {
                "../outside.txt": {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            },
        }
        output.writestr("manifest.json", json.dumps(manifest))
        output.writestr("data/../outside.txt", payload)

    with pytest.raises(ValueError, match="Unsafe backup path"):
        verify_backup(archive)


def test_backup_cli_create_verify_and_restore(monkeypatch, tmp_path, capsys) -> None:
    source = tmp_path / "data"
    source.mkdir()
    (source / "analysis_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(source))
    archive = tmp_path / "stockfinder.zip"
    restored = tmp_path / "restored"

    assert main(["create", str(archive)]) == 0
    assert main(["verify", str(archive)]) == 0
    assert main(["restore", str(archive), str(restored)]) == 0

    output = capsys.readouterr().out
    assert "Backup created" in output
    assert "Backup verified: 1 files" in output
    assert "Backup restored" in output
    assert (restored / "analysis_config.json").read_text(encoding="utf-8") == "{}"