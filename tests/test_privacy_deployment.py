from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from balagh import database, store
from balagh.backup import make_backup, restore_backup
from balagh.integration import DisabledGovernmentAdapter, ReviewedCaseExport
from balagh.privacy import purge_expired
from balagh.triage import ReportInput


class PrivacyDeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.data = self.path / "data"
        self.data_patch = patch.object(database, "DATA_DIR", self.data)
        self.db_patch = patch.object(database, "DB_PATH", self.data / "balagh.db")
        self.data_patch.start(); self.db_patch.start(); database.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop(); self.data_patch.stop(); self.temp.cleanup()

    def test_encrypted_backup_restores_into_empty_directory(self) -> None:
        report_id, _ = store.submit_report(ReportInput("تجريبي", "بلاغ اصطناعي", "الرياض", "الروابي"), "hash-1")
        encrypted = self.path / "backup.enc"
        make_backup(encrypted, "a-strong-backup-passphrase")
        self.assertNotIn("بلاغ اصطناعي".encode(), encrypted.read_bytes())
        restored = self.path / "restored"
        restore_backup(encrypted, restored, "a-strong-backup-passphrase")
        with closing(sqlite3.connect(restored / "balagh.db")) as connection:
            self.assertEqual(connection.execute("SELECT id FROM reports").fetchone()[0], report_id)
        with self.assertRaises(ValueError):
            restore_backup(encrypted, restored, "a-strong-backup-passphrase")

    def test_retention_deletes_only_old_closed_case_and_orphan_upload(self) -> None:
        upload_dir = self.data / "uploads"
        upload_dir.mkdir()
        attachment = upload_dir / "synthetic.png"
        attachment.write_bytes(b"synthetic")
        old_id, _ = store.submit_report(ReportInput("قديم", "بلاغ قديم", "الرياض", "الروابي"), "hash-1", str(attachment))
        live_id, _ = store.submit_report(ReportInput("جديد", "بلاغ مفتوح", "الرياض", "الروابي"), "hash-2")
        with database._connection() as connection:
            connection.execute("UPDATE reports SET status='Closed',updated_at='2020-01-01' WHERE id=?", (old_id,))
            connection.commit()
        self.assertEqual(purge_expired(365)["deleted_cases"], 0)
        result = purge_expired(365, apply=True)
        self.assertEqual(result["deleted_cases"], 1)
        self.assertIsNone(database.get_report(old_id))
        self.assertIsNotNone(database.get_report(live_id))
        self.assertFalse(attachment.exists())

    def test_government_adapter_is_disabled_and_idempotency_key_stable(self) -> None:
        args = dict(report_id=1, decision_id=2, category_ids=("roads_sidewalks",),
                    priority="Medium", city_id="riyadh", district="الروابي",
                    description="بلاغ اصطناعي", latitude=None, longitude=None)
        first = ReviewedCaseExport.from_reviewed_case(**args)
        second = ReviewedCaseExport.from_reviewed_case(**args)
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        with self.assertRaises(RuntimeError):
            DisabledGovernmentAdapter().submit(first)


if __name__ == "__main__":
    unittest.main()
