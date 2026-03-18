from __future__ import annotations

from sqlalchemy.orm import Session

from ghstats.web.models import Report, ReportJob


def enqueue_report_job(
    session: Session,
    *,
    report: Report,
    job_type: str,
    sample_data: bool,
) -> ReportJob:
    job = ReportJob(
        report_id=report.id,
        status="queued",
        job_type=job_type,
        sample_data=sample_data,
    )
    session.add(job)
    session.flush()
    report.latest_job_id = job.id
    report.status = "queued"
    return job
