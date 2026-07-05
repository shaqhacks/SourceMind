"""SQLAlchemy engine, session factory, and declarative base for SourceMind."""

from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from SourceMind.backend import config

# Revision id of the hand-written baseline migration (backend/db/migrations/
# versions/0001_baseline.py), capturing the schema as it existed before
# Alembic was introduced. Pre-existing databases (tables present, no
# alembic_version table) are stamped here before upgrading to head.
_BASELINE_REVISION = "0001"

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def db_url() -> str:
    """Return the database URL, falling back to the default SQLite path."""
    return config.db_url()


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


# Per-URL engine + sessionmaker cache.  Populated lazily by _session_factory_for_url().
# Tests that monkeypatch SOURCEMIND_DB_URL can pop their URL from this dict to
# ensure a clean engine is created for their tmp-path database.
_engine_cache: dict[str, tuple[Engine, sessionmaker[Session]]] = {}


def reset_engine_cache() -> None:
    """Dispose every cached engine and clear the cache.

    Call this in test teardown to ensure no open database connections linger
    across tests (prevents ResourceWarning: unclosed database).
    """
    for eng, _ in _engine_cache.values():
        eng.dispose()
    _engine_cache.clear()


def _session_factory_for_url(url: str) -> sessionmaker[Session]:
    """Return a cached sessionmaker for *url*, creating one on first access."""
    if url not in _engine_cache:
        eng = make_engine(url)
        factory: sessionmaker[Session] = sessionmaker(eng, autocommit=False, autoflush=False)
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
        factory: sessionmaker[Session] = sessionmaker(engine, autocommit=False, autoflush=False)
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


def _alembic_config() -> AlembicConfig:
    """Return an Alembic Config pointed at backend/db/migrations.

    script_location is always set explicitly (absolute path) so this works
    regardless of the process's current working directory; alembic.ini itself
    carries no ``sqlalchemy.url`` (see its comments) since the URL is supplied
    per-call via a shared connection (see ``_run_alembic``).
    """
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return cfg


def _run_alembic(engine: Engine, fn) -> None:
    """Run an Alembic command against *engine*, sharing a single connection.

    Passing the live connection (rather than a URL string) through
    ``config.attributes`` is what makes this correct for ``sqlite://:memory:``
    engines too: a fresh engine built from the URL string would open an
    unrelated, empty in-memory database.
    """
    cfg = _alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        fn(cfg)


def _alembic_stamp(engine: Engine, revision: str) -> None:
    _run_alembic(engine, lambda cfg: command.stamp(cfg, revision))


def _alembic_upgrade(engine: Engine, revision: str = "head") -> None:
    _run_alembic(engine, lambda cfg: command.upgrade(cfg, revision))


def init_db(eng: Engine | None = None) -> None:
    """Bring the database up to the current schema, via Alembic where needed.

    Two call shapes:

    - ``init_db(eng)`` with an explicit engine (the test-fixture path): always
      does a fast ``create_all`` + ``stamp head``, skipping state inspection,
      since callers passing an explicit engine are always working against a
      brand-new database (a fresh tmp-path SQLite file).
    - ``init_db()`` with no engine (the production/app-startup path, and any
      caller relying on the current ``db_url()``): inspects the target
      database and picks one of three paths so both fresh installs and
      pre-Alembic databases converge on the same schema:

      1. No tables at all (fresh DB) -> ``create_all`` from the current
         models, then stamp at ``head`` (create_all already produces the
         current schema, so there is nothing to actually migrate).
      2. Tables exist but no ``alembic_version`` table (a database created by
         a pre-Alembic ``create_all``) -> stamp at the baseline revision (the
         schema it actually has), then ``upgrade head`` to apply every
         migration since baseline.
      3. Already Alembic-managed -> ``upgrade head``.
    """
    if eng is not None:
        Base.metadata.create_all(eng)
        _alembic_stamp(eng, "head")
        return

    url = db_url()
    _session_factory_for_url(url)  # ensures URL is in cache
    target = _engine_cache[url][0]

    existing_tables = set(inspect(target).get_table_names())
    has_alembic_version = "alembic_version" in existing_tables
    has_app_tables = bool(existing_tables - {"alembic_version"})

    if not has_app_tables:
        Base.metadata.create_all(target)
        _alembic_stamp(target, "head")
    elif not has_alembic_version:
        _alembic_stamp(target, _BASELINE_REVISION)
        _alembic_upgrade(target, "head")
    else:
        _alembic_upgrade(target, "head")
