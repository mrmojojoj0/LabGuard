from logging.config import fileConfig
import os
import sys
from dotenv import load_dotenv

load_dotenv()

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from labguard_server.config import Settings
from labguard_server.db import Base
from labguard_server import models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline():
    url = Settings.from_env().database_url
    if not url:
        raise RuntimeError("DATABASE_URL must be configured")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"}, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = Settings.from_env().database_url or ""
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
