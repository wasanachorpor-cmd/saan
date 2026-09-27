"""SQLite engine and session factory."""

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

log = logging.getLogger(__name__)

SessionLocal: sessionmaker[Session] | None = None
engine: Engine | None = None


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def init_db(url: str) -> None:
    """Create the engine, tables, and bind SessionLocal."""
    global engine, SessionLocal
    engine = create_engine(url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    from app import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _migrate(engine)


_EXTRA_COLUMNS = {
    "users": {
        "trust": "INTEGER NOT NULL DEFAULT 50",
        "auth_provider": "VARCHAR(20) NOT NULL DEFAULT 'email'",
        "provider_subject": "VARCHAR(120)",
        "suspended_at": "DATETIME",
    },
    "documents": {
        "layout_kind": "VARCHAR(24)",
        "image_purge_at": "DATETIME",
        "image_purged_at": "DATETIME",
    },
    "edit_history": {
        "review_state": "VARCHAR(20) NOT NULL DEFAULT 'live'",
    },
}


def _migrate(bound: Engine) -> None:
    """Add columns that create_all does not attach to an existing SQLite file."""
    inspector = inspect(bound)
    with bound.begin() as connection:
        for table, columns in _EXTRA_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, declaration in columns.items():
                if name in present:
                    continue
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"))
                log.info("Added %s.%s", table, name)


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise RuntimeError("Database is not initialized")
    db = SessionLocal()
    try:
        try:
            from app.services.documents import purge_expired_images

            purge_expired_images(db)
        except Exception:
            log.exception("Image purge skipped")
        yield db
    finally:
        db.close()
