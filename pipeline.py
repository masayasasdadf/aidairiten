"""
案件の流れ:
  スクレイピング → DB保存（NEW）→ 分析（ANALYZING）→ 判定
    inhouse  → 実行（IN_PROGRESS）→ 品質チェック（QC）→ 承認待ち（PENDING_APPROVAL）
    outsource → OUTSOURCE（発注先リスト待ち）
    skip     → SKIPPED
"""

import asyncio
import json
from datetime import datetime

from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Job, Deliverable, JobStatus, JobCategory, ExecutionType
from scrapers.monitor import run_all_scrapers
from scrapers.base import RawJob
from agents.analysis_agent import analyze_job
from agents.execution_agent import execute_job
from agents.quality_agent import check_quality


def _upsert_job(db: Session, raw: RawJob) -> tuple[Job, bool]:
    existing = db.query(Job).filter(Job.external_id == raw.external_id).first()
    if existing:
        return existing, False

    job = Job(
        platform=raw.platform,
        external_id=raw.external_id,
        url=raw.url,
        title=raw.title,
        description=raw.description,
        price_min=raw.price_min,
        price_max=raw.price_max,
        price_fixed=raw.price_fixed,
        deadline=raw.deadline,
        client_name=raw.client_name,
        skills_required=json.dumps(raw.skills_required, ensure_ascii=False),
        status=JobStatus.NEW,
        discovered_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job, True


async def _analyze(db: Session, job: Job):
    job.status = JobStatus.ANALYZING
    db.commit()

    from scrapers.base import RawJob as R
    raw = R(
        platform=job.platform,
        external_id=job.external_id or "",
        url=job.url or "",
        title=job.title,
        description=job.description or "",
        price_min=job.price_min,
        price_max=job.price_max,
        price_fixed=job.price_fixed,
    )

    result = await analyze_job(raw)

    job.category = JobCategory(result["category"]) if result["category"] in JobCategory._value2member_map_ else JobCategory.OTHER
    job.score = result["score"]
    job.analysis_notes = result["analysis_notes"]
    job.skills_required = json.dumps(result["skills_required"], ensure_ascii=False)

    execution = result["execution_type"]
    if execution == "inhouse":
        job.execution_type = ExecutionType.INHOUSE
        job.status = JobStatus.INHOUSE
    elif execution == "outsource":
        job.execution_type = ExecutionType.OUTSOURCE
        job.status = JobStatus.OUTSOURCE
    else:
        job.status = JobStatus.SKIPPED

    db.commit()
    print(f"[Pipeline] 分析完了 '{job.title[:30]}' → {job.status.value} (score={job.score:.0f})")


async def _execute(db: Session, job: Job):
    job.status = JobStatus.IN_PROGRESS
    db.commit()

    content = await execute_job(job)

    job.status = JobStatus.QC
    db.commit()

    qc_result = await check_quality(job, content)

    deliverable = db.query(Deliverable).filter(Deliverable.job_id == job.id).first()
    if deliverable:
        deliverable.content = content
        deliverable.qc_passed = qc_result["passed"]
        deliverable.qc_notes = json.dumps(qc_result, ensure_ascii=False)
        deliverable.updated_at = datetime.utcnow()
    else:
        deliverable = Deliverable(
            job_id=job.id,
            content=content,
            qc_passed=qc_result["passed"],
            qc_notes=json.dumps(qc_result, ensure_ascii=False),
        )
        db.add(deliverable)

    if qc_result["passed"]:
        job.status = JobStatus.PENDING_APPROVAL
        print(f"[Pipeline] QC合格 '{job.title[:30]}' → 承認待ち")
    else:
        job.status = JobStatus.REJECTED
        print(f"[Pipeline] QC不合格 '{job.title[:30]}': {qc_result['summary']}")

    db.commit()


async def run_pipeline():
    print(f"[Pipeline] 開始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 案件収集
    raw_jobs = await run_all_scrapers()
    print(f"[Pipeline] 合計 {len(raw_jobs)} 件取得")

    # 2. DB保存 + 分析
    db = SessionLocal()
    new_jobs = []
    try:
        for raw in raw_jobs:
            job, is_new = _upsert_job(db, raw)
            if is_new:
                new_jobs.append(job)
    finally:
        db.close()

    print(f"[Pipeline] 新規案件 {len(new_jobs)} 件")

    # 3. 分析（並行・最大5件同時）
    sem = asyncio.Semaphore(5)
    async def analyze_with_sem(job_id: int):
        async with sem:
            db = SessionLocal()
            try:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    await _analyze(db, job)
            finally:
                db.close()

    await asyncio.gather(*[analyze_with_sem(j.id) for j in new_jobs])

    # 4. 自社処理案件を実行（スコア70以上のもの）
    db = SessionLocal()
    try:
        inhouse_jobs = (
            db.query(Job)
            .filter(Job.status == JobStatus.INHOUSE, Job.score >= 70)
            .all()
        )
        inhouse_ids = [j.id for j in inhouse_jobs]
    finally:
        db.close()

    print(f"[Pipeline] 自社処理対象 {len(inhouse_ids)} 件（スコア70以上）")

    async def execute_with_sem(job_id: int):
        async with sem:
            db = SessionLocal()
            try:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    await _execute(db, job)
            finally:
                db.close()

    await asyncio.gather(*[execute_with_sem(jid) for jid in inhouse_ids])

    print(f"[Pipeline] 完了")
