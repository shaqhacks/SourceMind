"""Lazy, cached SQLAlchemy engine/session factory.

The engine is created on first use (not at import time) so that tests can
set SMV2_DB_URL and call dispose_engine() to force a fresh engine bound to
the new URL. Every raw DBAPI connection gets foreign keys, WAL, and a busy
timeout applied via a connect-event listener — this must hold for every
connection the pool hands out, not just the first.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import db_url

_engine: Engine | None = None
_engine_url: str | None = None
_session_factory: sessionmaker[Session] | None = None


def _apply_sqlite_pragmas(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def get_engine() -> Engine:
    global _engine, _engine_url, _session_factory
    current_url = db_url()
    if _engine is not None and _engine_url == current_url:
        return _engine

    if _engine is not None:
        _engine.dispose()

    connect_args = {}
    if current_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine_with_pragmas(current_url, connect_args)
    _engine = engine
    _engine_url = current_url
    _session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine


def create_engine_with_pragmas(url: str, connect_args: dict):
    from sqlalchemy import create_engine

    engine = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _apply_sqlite_pragmas)
    return engine


def get_session() -> Session:
    get_engine()  # ensure engine + session factory are initialized for current URL
    assert _session_factory is not None
    return _session_factory()


def dispose_engine() -> None:
    global _engine, _engine_url, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None
    _session_factory = None
