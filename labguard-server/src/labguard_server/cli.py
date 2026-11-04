import argparse
from getpass import getpass
from dotenv import load_dotenv

from labguard_server.config import Settings
from labguard_server.db import Base, make_session_factory
from labguard_server.models import Administrator
from labguard_server.security import hash_password


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog="labguard-server")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Create the first or another administrator")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=["VIEWER", "OPERATOR", "LAB_ADMIN", "SUPER_ADMIN"], default="SUPER_ADMIN")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    password = getpass("Administrator password: ")
    confirm = getpass("Confirm password: ")
    if len(password) < 12 or password != confirm:
        parser.error("Passwords must match and contain at least 12 characters")
    engine, factory = make_session_factory(settings.database_url)
    try:
        with factory.begin() as db:
            db.add(Administrator(username=args.username.strip().casefold(), password_hash=hash_password(password), role=args.role))
        print("Administrator created")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
