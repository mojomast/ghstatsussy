from __future__ import annotations

import time

from ghstats.web.config import load_web_settings
from ghstats.web.database import create_engine_and_session_factory
from ghstats.web.jobs import delete_expired_reports, process_next_job


def run() -> None:
    settings = load_web_settings()
    settings.report_storage_dir.mkdir(parents=True, exist_ok=True)
    _, session_factory = create_engine_and_session_factory(settings.database_url)

    while True:
        with session_factory() as session:
            processed = process_next_job(settings, session)
            delete_expired_reports(session)
        if processed is None:
            time.sleep(1.0)


if __name__ == "__main__":
    run()
