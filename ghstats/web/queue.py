from __future__ import annotations

from sqlalchemy.orm import Session

from ghstats.web.models import Report, ReportJob


def enqueue_report_job(
    session: Session,
    *,
    report: Report,
    job_type: str,
    sample_data: bool,
    payload_json: dict | None = None,
    export_id: str | None = None,
    set_latest_job: bool = True,
    update_report_status: bool = True,
) -> ReportJob:
    job = ReportJob(
        report_id=report.id,
        status="queued",
        job_type=job_type,
        sample_data=sample_data,
        payload_json=payload_json,
        export_id=export_id,
    )
    session.add(job)
    session.flush()
    if set_latest_job:
        report.latest_job_id = job.id
    if update_report_status:
        report.status = "queued"
    return job
