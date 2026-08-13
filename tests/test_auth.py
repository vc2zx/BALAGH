from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from balagh.auth import verify_staff_access


class AuthTests(unittest.TestCase):
    def test_correct_access_code_is_accepted(self) -> None:
        with patch.dict(
            os.environ,
            {"STAFF_ACCESS_CODE": "202608"},
            clear=False,
        ):
            self.assertTrue(verify_staff_access("202608"))

    def test_wrong_access_code_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"STAFF_ACCESS_CODE": "202608"},
            clear=False,
        ):
            self.assertFalse(verify_staff_access("123456"))

    def test_change_me_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"STAFF_ACCESS_CODE": "change-me"},
            clear=False,
        ):
            self.assertFalse(verify_staff_access("change-me"))

    def test_missing_access_code_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(verify_staff_access("anything"))


if __name__ == "__main__":
    unittest.main()