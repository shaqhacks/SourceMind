"""Alembic environment script for SourceMind.

Resolves the database URL at runtime rather than from a hardcoded
``sqlalchemy.url`` in alembic.ini:

- When driven from ``backend/db/base.py`` (the normal path — startup, tests),
  the caller passes a live ``Connection`` via ``config.attributes["connection"]``
  and this file reuses it directly, so it always operates on the same engine
  the application is using (important for the ``:memory:`` SQLite case, where
  a fresh engine built from the URL string would be a completely different
  empty database).
- When invoked directly via the ``alembic`` CLI for local development, no
  connection is attributes-injected, so this file falls back to building an
  engine from ``SOURCEMIND_DB_URL`` (via backend/config.py) with the same
  default as the rest of the app.
"""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from SourceMind.backend import config as app_config
from SourceMind.backend.db import models  # noqa: F401 - registers tables on Base.metadata
from SourceMind.backend.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    return config.get_main_option("sqlalchemy.url") or app_config.db_url()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection.

    Reuses ``config.attributes["connection"]`` when the caller supplied one
    (the app's own engine/connection); otherwise builds a fresh engine from
    the resolved URL for standalone CLI use.
    """
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
