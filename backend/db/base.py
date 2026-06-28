"""SQLAlchemy engine, session factory, and declarative base for SourceMind."""

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def db_url() -> str:
    """Return the database URL, falling back to the default SQLite path."""
    return os.environ.get("SOURCEMIND_DB_URL", "sqlite:///data/sourcemind.db")


def make_engine(url: str | None = None):
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
engine = make_engine()
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session():
    """Yield a database session, committing on success and rolling back on error."""
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(eng=None) -> None:
    """Create all tables defined on Base.metadata against the given engine.

    If *eng* is None the module-level ``engine`` is used.
    """
    target = eng if eng is not None else engine
    Base.metadata.create_all(target)
