"""Schema management entry point.

Schema changes only ever happen through Alembic revisions. init_db() upgrades
whatever DB is at db_url() to head — this covers both a brand-new DB (alembic
creates alembic_version and applies every revision from base) and an
already-managed DB (alembic sees it's already at head and no-ops). Never call
Base.metadata.create_all() against a DB that might already exist.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import data_dir, db_url

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url())
    return cfg


def init_db() -> None:
    url = db_url()
    if url.startswith("sqlite:///"):
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        data_dir().mkdir(parents=True, exist_ok=True)

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
