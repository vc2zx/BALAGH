from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from balagh import database
from balagh.auth import authenticate, can_access, consume_rate_limit, create_user, get_user


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name)
        self.data_patch = patch.object(database, "DATA_DIR", self.data)
        self.db_patch = patch.object(database, "DB_PATH", self.data / "test.db")
        self.data_patch.start(); self.db_patch.start()
        database.init_db()

    def tearDown(self) -> None:
        self.db_patch.stop(); self.data_patch.stop(); self.temp.cleanup()

    def test_individual_account_authentication_and_jurisdiction(self) -> None:
        user_id = create_user("reviewer_1", "a-long-private-passphrase", "reviewer", ["riyadh"])
        self.assertIsNone(authenticate("reviewer_1", "wrong"))
        user = authenticate("reviewer_1", "a-long-private-passphrase")
        self.assertEqual(user["id"], user_id)
        self.assertTrue(can_access(user, "riyadh", write=True))
        self.assertFalse(can_access(user, "jeddah", write=True))
        with database._connection() as connection:
            connection.execute("UPDATE staff_users SET active=0 WHERE id=?", (user_id,))
            connection.commit()
        self.assertIsNone(get_user(user_id))

    def test_viewer_cannot_write_and_password_length_is_checked(self) -> None:
        with self.assertRaises(ValueError):
            create_user("short", "short", "admin", [])
        user_id = create_user("viewer", "another-private-passphrase", "viewer", ["jeddah"])
        self.assertTrue(can_access(get_user(user_id), "jeddah"))
        self.assertFalse(can_access(get_user(user_id), "jeddah", write=True))

    def test_rate_limit_is_shared_in_database(self) -> None:
        self.assertTrue(consume_rate_limit("login", "127.0.0.1", 2, 900))
        self.assertTrue(consume_rate_limit("login", "127.0.0.1", 2, 900))
        self.assertFalse(consume_rate_limit("login", "127.0.0.1", 2, 900))


if __name__ == "__main__":
    unittest.main()
