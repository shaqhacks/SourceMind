from __future__ import annotations

from sqlalchemy import text

from app.db.engine import get_session


def test_foreign_keys_pragma_is_enabled_for_new_sessions(client):
    """Cascade deletes silently no-op if this pragma isn't actually ON for
    the connections the app uses — this is the regression guard for that.
    """
    session = get_session()
    try:
        result = session.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1
    finally:
        session.close()
