from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def create_engine_and_session_factory(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    connect_args = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(database_url, connect_args=connect_args)
    if database_url.startswith("sqlite"):
        _run_sqlite_migrations(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return engine, session_factory


def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _run_sqlite_migrations(engine: Engine) -> None:
    with engine.begin() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "reports" not in tables:
            return

        report_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(reports)")
        }
        if "presentation_config" not in report_columns:
            connection.exec_driver_sql(
                "ALTER TABLE reports ADD COLUMN presentation_config JSON DEFAULT NULL"
            )
        if "template_key" not in report_columns:
            connection.exec_driver_sql(
                "ALTER TABLE reports ADD COLUMN template_key VARCHAR(32) NOT NULL DEFAULT 'default'"
            )
