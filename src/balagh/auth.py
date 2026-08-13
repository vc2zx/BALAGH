from __future__ import annotations

import hmac
import os

from dotenv import load_dotenv


load_dotenv()


def verify_staff_access(code: str) -> bool:
    """Prototype-only local access-code check for the staff portal."""
    expected = os.getenv("STAFF_ACCESS_CODE", "").strip()

    if not expected or expected == "change-me":
        return False

    return hmac.compare_digest(str(code or ""), expected)