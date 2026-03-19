from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ghstats.config import RuntimeConfig, StaticTokenProvider
from ghstats.service import GhStatsService
from ghstats.utils.timeparse import build_time_window
from ghstats.web.config import WebAppSettings
from ghstats.web.models import Report, ReportExport, ReportJob, ReportSnapshot, User
from ghstats.web.serialization import json_default
from ghstats.export.service import ReportExportService


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def process_next_job(settings: WebAppSettings, session: Session) -> ReportJob | None:
    recover_stale_jobs(settings, session)
    job = (
        session.query(ReportJob)
        .filter(ReportJob.status == "queued")
        .order_by(ReportJob.created_at.asc())
        .first()
    )
    if job is None:
        return None

    report = session.get(Report, job.report_id)
    if report is None:
        job.status = "failed"
        job.error_message = "Report no longer exists."
        job.finished_at = utcnow()
        session.commit()
        return job


def recover_stale_jobs(settings: WebAppSettings, session: Session) -> int:
    cutoff = utcnow() - timedelta(seconds=settings.stale_job_timeout_seconds)
    stale_jobs = (
        session.query(ReportJob)
        .filter(ReportJob.status == "running", ReportJob.started_at.is_not(None), ReportJob.started_at < cutoff)
        .all()
    )
    recovered = 0
    for job in stale_jobs:
        report = session.get(Report, job.report_id)
        if report is None:
            job.status = "failed"
            job.error_message = "Recovered stale job for missing report."
            job.finished_at = utcnow()
            recovered += 1
            continue

        if job.job_type.startswith("export:"):
            export_record = session.get(ReportExport, job.export_id) if job.export_id else None
            if export_record is not None and export_record.status == "running":
                export_record.status = "queued"
                export_record.error_message = None
                export_record.completed_at = None
        else:
            report.status = "queued"
            report.error_message = None

        job.status = "queued"
        job.started_at = None
        job.finished_at = None
        job.error_message = None
        recovered += 1

    if recovered:
        session.commit()
    return recovered

    user = session.get(User, report.user_id)
    if user is None:
        job.status = "failed"
        report.status = "failed"
        job.error_message = "User no longer exists."
        job.finished_at = utcnow()
        session.commit()
        return job

    try:
        job.status = "running"
        job.attempts += 1
        job.started_at = utcnow()
        if not job.job_type.startswith("export:"):
            report.status = "running"
            report.error_message = None
        session.commit()

        if job.job_type.startswith("export:"):
            _process_export_job(settings, session, report, job)
        else:
            _process_report_generation_job(settings, session, report, user, job)
        return job
    except Exception as error:
        job.status = "failed"
        job.error_message = str(error)
        job.finished_at = utcnow()
        if job.job_type.startswith("export:"):
            export_record = session.get(ReportExport, job.export_id) if job.export_id else None
            if export_record is not None:
                export_record.status = "failed"
                export_record.error_message = str(error)
                export_record.completed_at = utcnow()
        else:
            report.status = "failed"
            report.error_message = str(error)
        session.commit()
        return job


def delete_expired_reports(session: Session) -> int:
    now = utcnow()
    reports = (
        session.query(Report)
        .filter(Report.expires_at.is_not(None), Report.expires_at < now)
        .all()
    )
    count = len(reports)
    for report in reports:
        session.delete(report)
    session.commit()
    return count


def _process_report_generation_job(
    settings: WebAppSettings,
    session: Session,
    report: Report,
    user: User,
    job: ReportJob,
) -> None:
    token = None if job.sample_data else _decrypt_user_token(settings, user)
    runtime_config = RuntimeConfig(
        token_provider=StaticTokenProvider(token),
        include_private=report.include_private,
    )
    service = GhStatsService(runtime_config)
    artifacts = service.build_artifacts(
        window=build_time_window(report.since_spec),
        sample_data=job.sample_data,
        template_key=report.template_key,
        presentation_config=report.presentation_config,
    )

    next_version = 1 + max((snapshot.version for snapshot in report.snapshots), default=0)
    snapshot_dir = settings.report_storage_dir / report.slug / f"v{next_version}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    html_path = snapshot_dir / "report.html"
    html_path.write_text(artifacts.html, encoding="utf-8")

    render_document_file = snapshot_dir / "render_document.json"
    render_document_file.write_text(
        json.dumps(artifacts.context, indent=2, default=json_default),
        encoding="utf-8",
    )

    json_path: str | None = None
    if report.store_metadata:
        json_file = snapshot_dir / "report.json"
        json_file.write_text(
            json.dumps(
                {
                    "dataset": artifacts.dataset.to_dict(),
                },
                indent=2,
                default=json_default,
            ),
            encoding="utf-8",
        )
        json_path = str(json_file)

    snapshot = ReportSnapshot(
        report_id=report.id,
        version=next_version,
        html_path=str(html_path),
        json_path=json_path,
        contains_private_data=report.include_private,
        restricted_contributions_count=artifacts.dataset.restricted_contributions_count,
    )
    session.add(snapshot)
    session.flush()

    report.latest_snapshot_id = snapshot.id
    report.generated_at = snapshot.created_at
    report.status = "ready"
    report.error_message = None
    if report.expires_at is None:
        report.expires_at = utcnow() + timedelta(days=settings.default_report_expiry_days)

    job.status = "succeeded"
    job.finished_at = utcnow()
    session.commit()


def _process_export_job(
    settings: WebAppSettings,
    session: Session,
    report: Report,
    job: ReportJob,
) -> None:
    export_record = session.get(ReportExport, job.export_id) if job.export_id else None
    if export_record is None:
        raise RuntimeError("Export record no longer exists.")
    export_record.status = "running"
    export_record.error_message = None
    session.commit()

    export_service = ReportExportService(settings, session)
    export_service.execute_export(export_record)
    job.status = "succeeded"
    job.finished_at = utcnow()
    session.commit()


def _decrypt_user_token(settings: WebAppSettings, user: User) -> str:
    from ghstats.web.crypto import TokenCipher

    return TokenCipher(settings.secret_key).decrypt(user.access_token_encrypted)
