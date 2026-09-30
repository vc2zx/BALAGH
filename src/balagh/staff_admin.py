"""Provision individual staff users without putting passwords in shell history."""
from __future__ import annotations

import argparse
import getpass

from balagh import database
from balagh.auth import create_user


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=["admin", "reviewer", "viewer"], required=True)
    create.add_argument("--city", action="append", default=[])
    disable = sub.add_parser("disable-user")
    disable.add_argument("--username", required=True)
    args = parser.parse_args()
    database.init_db()
    if args.command == "create-user":
        password = getpass.getpass("Password (14+ characters): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords did not match")
        user_id = create_user(args.username, password, args.role, args.city)
        print(f"Created staff user #{user_id}: {args.username}")
    else:
        with database._connection() as connection:
            changed = connection.execute("UPDATE staff_users SET active=0 WHERE username=?",
                                         (args.username.strip().lower(),))
            connection.commit()
        print("Disabled" if changed.rowcount else "No matching user")


if __name__ == "__main__":
    main()
