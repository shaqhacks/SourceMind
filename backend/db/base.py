"""SQLAlchemy engine, session factory, and declarative base for SourceMind."""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def db_url() -> str:
    """Return the database URL, falling back to the default SQLite path."""
    return os.environ.get("SOURCEMIND_DB_URL", "sqlite:///data/sourcemind.db")


def make_engine(url: str | None = None) -> Engine:
    """Create and return a SQLAlchemy engine.

    For SQLite URLs the parent directory is created automatically and
    ``check_same_thread`` is disabled so the engine can be shared across
    request threads.
    """
    resolved_url = url or db_url()

    kwargs: dict = {}
    if resolved_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        # Ensure the parent directory exists for file-based SQLite paths.
        # Strip the leading "sqlite:///" (or "sqlite://" for in-memory).
        db_path_str = resolved_url.replace("sqlite:///", "").replace("sqlite://", "")
        if db_path_str and db_path_str != ":memory:":
            Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)

    return create_engine(resolved_url, **kwargs)


# Module-level engine and session factory, constructed from the current env.
# Kept for application convenience — do NOT rely on these inside get_session().
engine = make_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Per-URL engine + sessionmaker cache.  Populated lazily by _session_factory_for_url().
# Tests that monkeypatch SOURCEMIND_DB_URL can pop their URL from this dict to
# ensure a clean engine is created for their tmp-path database.
_engine_cache: dict[str, tuple[Engine, sessionmaker[Session]]] = {}


def _session_factory_for_url(url: str) -> sessionmaker[Session]:
    """Return a cached sessionmaker for *url*, creating one on first access."""
    if url not in _engine_cache:
        eng = make_engine(url)
        factory: sessionmaker[Session] = sessionmaker(bind=eng, autocommit=False, autoflush=False)
        _engine_cache[url] = (eng, factory)
    return _engine_cache[url][1]


@contextmanager
def get_session(engine: Engine | None = None):
    """Yield a database session, committing on success and rolling back on error.

    If *engine* is provided it is used directly; otherwise the session factory
    is resolved from the current ``db_url()`` at call time (cached per distinct
    URL so connection-pool state is preserved across calls with the same URL).
    This means tests that monkeypatch ``SOURCEMIND_DB_URL`` after import will
    automatically receive sessions connected to the patched database.
    """
    if engine is not None:
        factory: sessionmaker[Session] = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    else:
        factory = _session_factory_for_url(db_url())
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(eng: Engine | None = None) -> None:
    """Create all tables defined on Base.metadata against the given engine.

    If *eng* is None the engine for the current ``db_url()`` is used (fetched
    from the per-URL cache, creating it if necessary).
    """
    if eng is not None:
        target = eng
    else:
        url = db_url()
        _session_factory_for_url(url)  # ensures URL is in cache
        target = _engine_cache[url][0]
    Base.metadata.create_all(target)
