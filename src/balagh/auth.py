"""Individual staff accounts and durable rate limits."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from balagh import database
from balagh.catalog import catalog


def create_user(username: str, password: str, role: str, city_ids: list[str]) -> int:
    username = username.strip().lower()
    if not username or len(username) > 60 or not username.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Invalid username")
    if len(password) < 14:
        raise ValueError("Password must be at least 14 characters")
    if role not in {"admin", "reviewer", "viewer"}:
        raise ValueError("Invalid role")
    if any(city not in catalog()["jurisdictions"] for city in city_ids):
        raise ValueError("Unknown jurisdiction")
    if role != "admin" and not city_ids:
        raise ValueError("A non-admin account needs a jurisdiction")
    with database._connection() as connection:
        cursor = connection.execute("""INSERT INTO staff_users
            (username,password_hash,role,city_ids_json,created_at) VALUES (?,?,?,?,?)""",
            (username, generate_password_hash(password, method="scrypt"), role,
             json.dumps(sorted(set(city_ids))), datetime.now(timezone.utc).isoformat()))
        connection.commit()
        return int(cursor.lastrowid)


def get_user(user_id: int) -> dict | None:
    with database._connection() as connection:
        row = connection.execute("SELECT id,username,role,city_ids_json,active FROM staff_users WHERE id=?",
                                 (user_id,)).fetchone()
    return {**dict(row), "city_ids": json.loads(row["city_ids_json"])} if row and row["active"] else None


def authenticate(username: str, password: str) -> dict | None:
    with database._connection() as connection:
        row = connection.execute("SELECT * FROM staff_users WHERE username=? AND active=1",
                                 (username.strip().lower(),)).fetchone()
    if row and check_password_hash(row["password_hash"], password):
        return get_user(int(row["id"]))
    return None


def can_access(user: dict, city_id: str | None, write: bool = False) -> bool:
    if write and user["role"] == "viewer":
        return False
    return user["role"] == "admin" or bool(city_id and city_id in user["city_ids"])


def consume_rate_limit(scope: str, identity: str, limit: int, seconds: int) -> bool:
    """Fixed-window SQLite limit shared by all application processes."""
    key = hashlib.sha256(f"{scope}:{identity}".encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT window_start,attempts FROM rate_limits WHERE key_hash=?",
                                 (key,)).fetchone()
        if row is None or datetime.fromisoformat(row["window_start"]) + timedelta(seconds=seconds) <= now:
            connection.execute("INSERT OR REPLACE INTO rate_limits (key_hash,window_start,attempts) VALUES (?,?,1)",
                               (key, now.isoformat()))
            allowed = True
        else:
            allowed = int(row["attempts"]) < limit
            connection.execute("UPDATE rate_limits SET attempts=attempts+1 WHERE key_hash=?", (key,))
        connection.commit()
    return allowed
