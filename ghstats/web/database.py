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

        if "report_jobs" in tables:
            report_job_columns = {
                row[1]
                for row in connection.exec_driver_sql("PRAGMA table_info(report_jobs)")
            }
            if "payload_json" not in report_job_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE report_jobs ADD COLUMN payload_json JSON DEFAULT NULL"
                )
            if "export_id" not in report_job_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE report_jobs ADD COLUMN export_id VARCHAR(36) DEFAULT NULL"
                )

        if "report_exports" not in tables:
            connection.exec_driver_sql(
                """
                CREATE TABLE report_exports (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    report_id VARCHAR(36) NOT NULL,
                    snapshot_id VARCHAR(36) NOT NULL,
                    owner_user_id VARCHAR(36) NOT NULL,
                    export_type VARCHAR(24) NOT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'queued',
                    presentation_hash VARCHAR(64) NOT NULL,
                    options_json JSON DEFAULT NULL,
                    artifact_path TEXT DEFAULT NULL,
                    mime_type VARCHAR(128) DEFAULT NULL,
                    byte_size INTEGER DEFAULT NULL,
                    error_message TEXT DEFAULT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    completed_at DATETIME DEFAULT NULL,
                    expires_at DATETIME DEFAULT NULL,
                    FOREIGN KEY(report_id) REFERENCES reports (id),
                    FOREIGN KEY(snapshot_id) REFERENCES report_snapshots (id),
                    FOREIGN KEY(owner_user_id) REFERENCES users (id)
                )
                """
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_report_exports_report_id ON report_exports (report_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_report_exports_snapshot_id ON report_exports (snapshot_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_report_exports_owner_user_id ON report_exports (owner_user_id)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_report_exports_export_type ON report_exports (export_type)"
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_report_exports_presentation_hash ON report_exports (presentation_hash)"
            )

        if "github_profile_publish_connections" not in tables:
            connection.exec_driver_sql(
                """
                CREATE TABLE github_profile_publish_connections (
                    user_id VARCHAR(36) NOT NULL PRIMARY KEY,
                    github_login VARCHAR(255) NOT NULL,
                    profile_repo_owner VARCHAR(255) NOT NULL,
                    profile_repo_name VARCHAR(255) NOT NULL,
                    app_installation_id INTEGER NOT NULL,
                    last_publish_commit_sha VARCHAR(64) DEFAULT NULL,
                    last_publish_at DATETIME DEFAULT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users (id)
                )
                """
            )
            connection.exec_driver_sql(
                "CREATE INDEX ix_github_profile_publish_connections_github_login ON github_profile_publish_connections (github_login)"
            )
