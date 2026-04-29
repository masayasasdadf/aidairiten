"""
案件の流れ:
  巡回(scrape) → DB保存(NEW)
    → 分析(ANALYZING) → 営業部の上申(REPORTED)  ← ここでユーザーのGOサインを待つ
        ユーザーGO  → execute(IN_PROGRESS) → QC → 承認待ち
        ユーザーSKIP → SKIPPED

巡回はスケジューラではなくユーザーの指示でのみ起動する。
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from db.database import SessionLocal
from db.models import Job, Deliverable, JobStatus, JobCategory, ExecutionType
from scrapers.monitor import run_all_scrapers
from scrapers.base import RawJob
from agents.analysis_agent import analyze_job
from agents.execution_agent import execute_job
from agents.quality_agent import check_quality
from dashboard.events import log_event


# ---- 並行制御 ----
_cycle_lock = asyncio.Lock()
_cycle_state: dict = {"running": False, "started_at": None, "phase": ""}


def cycle_state() -> dict:
    """現在の巡回サイクル状態を返す。UI が /api/cycle/state で参照。"""

    return {
        "running": _cycle_state["running"],
        "started_at": _cycle_state["started_at"].isoformat() + "Z" if _cycle_state["started_at"] else None,
        "phase": _cycle_state["phase"],
    }


def _set_phase(phase: str) -> None:
    _cycle_state["phase"] = phase


# ---- 内部処理 ----
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


async def _analyze_and_report(db: Session, job: Job) -> None:
    """分析エージェントで判断 → 結果に応じて REPORTED か SKIPPED に遷移。

    inhouse / outsource どちらの推奨であってもまず REPORTED にし、
    ユーザーの GO サインを待つ。skip は自動でスキップ。
    """

    job.status = JobStatus.ANALYZING
    db.commit()
    log_event("analysis", "分析中", job.title[:40], job_id=job.id)

    raw = RawJob(
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

    job.category = (
        JobCategory(result["category"])
        if result["category"] in JobCategory._value2member_map_
        else JobCategory.OTHER
    )
    job.score = float(result.get("score", 0))
    job.analysis_notes = result.get("analysis_notes", "")
    job.skills_required = json.dumps(result.get("skills_required", []), ensure_ascii=False)

    execution = result.get("execution_type", "skip")
    if execution == "inhouse":
        job.execution_type = ExecutionType.INHOUSE
        job.status = JobStatus.REPORTED
    elif execution == "outsource":
        job.execution_type = ExecutionType.OUTSOURCE
        job.status = JobStatus.REPORTED
    else:
        job.execution_type = None
        job.status = JobStatus.SKIPPED

    db.commit()

    if job.status == JobStatus.REPORTED:
        log_event(
            "analysis",
            "営業部上申",
            f"'{job.title[:30]}' → 推奨 {execution} / score={job.score:.0f}",
            job_id=job.id,
            level="success",
        )
    else:
        log_event(
            "analysis",
            "自動見送り",
            f"'{job.title[:30]}' → skip",
            job_id=job.id,
        )


async def _execute(db: Session, job: Job) -> None:
    job.status = JobStatus.IN_PROGRESS
    db.commit()
    log_event("execution", "生産中", job.title[:40], job_id=job.id)

    content = await execute_job(job)

    job.status = JobStatus.QC
    db.commit()
    log_event("qc", "QC中", job.title[:40], job_id=job.id)

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
        log_event("qc", "QC合格", f"'{job.title[:30]}' → 承認待ち", job_id=job.id, level="success")
    else:
        job.status = JobStatus.REJECTED
        log_event(
            "qc",
            "QC不合格",
            f"'{job.title[:30]}': {qc_result.get('summary', '')}",
            job_id=job.id,
            level="warn",
        )

    db.commit()


# ---- 公開関数 ----
async def run_pipeline() -> dict:
    """1サイクル巡回 → 上申まで。execute はユーザー GO 後。

    並行起動はロックでガード。停止中ならスキップ。
    """

    from db.control import is_paused

    paused, until, reason = is_paused()
    if paused:
        log_event(
            "pipeline",
            "業務停止中につきスキップ",
            f"再開予定 {until.strftime('%Y-%m-%d %H:%M UTC')} / 理由: {reason or '-'}",
            level="warn",
        )
        return {"ok": False, "reason": "paused"}

    if _cycle_lock.locked():
        log_event("pipeline", "巡回スキップ", "既に巡回中", level="warn")
        return {"ok": False, "reason": "already_running"}

    async with _cycle_lock:
        _cycle_state["running"] = True
        _cycle_state["started_at"] = datetime.utcnow()
        _set_phase("起動")
        try:
            log_event("pipeline", "巡回開始", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            # 1. 巡回
            _set_phase("巡回")
            raw_jobs = await run_all_scrapers()
            log_event("pipeline", "巡回完了", f"合計 {len(raw_jobs)} 件")

            # 2. DB 保存
            _set_phase("DB保存")
            db = SessionLocal()
            new_jobs = []
            try:
                for raw in raw_jobs:
                    job, is_new = _upsert_job(db, raw)
                    if is_new:
                        new_jobs.append(job.id)
            finally:
                db.close()

            log_event("pipeline", "新規案件", f"{len(new_jobs)} 件")

            # 3. 分析 → 上申（並行最大5）
            _set_phase("分析・上申")
            sem = asyncio.Semaphore(5)

            async def analyze_with_sem(jid: int) -> None:
                async with sem:
                    db = SessionLocal()
                    try:
                        job = db.query(Job).filter(Job.id == jid).first()
                        if job:
                            await _analyze_and_report(db, job)
                    finally:
                        db.close()

            if new_jobs:
                await asyncio.gather(*[analyze_with_sem(jid) for jid in new_jobs])

            # 上申件数集計
            db = SessionLocal()
            try:
                reported_count = db.query(Job).filter(Job.status == JobStatus.REPORTED).count()
            finally:
                db.close()

            log_event(
                "pipeline",
                "サイクル完了",
                f"上申待ち {reported_count} 件",
                level="success",
            )
            return {"ok": True, "scraped": len(raw_jobs), "new": len(new_jobs), "reported_total": reported_count}
        finally:
            _cycle_state["running"] = False
            _cycle_state["started_at"] = None
            _set_phase("")


async def go_job(job_id: int) -> dict:
    """ユーザーの GO サイン。REPORTED な inhouse 案件を execute → QC まで進める。

    outsource 案件はそのまま OUTSOURCE 状態（発注先待ち）に遷移するのみで、
    LLM での生産はしない。
    """

    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"ok": False, "error": "案件が見つかりません"}
        if job.status != JobStatus.REPORTED:
            return {"ok": False, "error": f"GO できる状態ではありません (現在: {job.status.value})"}

        if job.execution_type == ExecutionType.OUTSOURCE:
            job.status = JobStatus.OUTSOURCE
            db.commit()
            log_event(
                "pipeline",
                "GOサイン受領 (外注)",
                f"'{job.title[:30]}' → 外注待ち",
                job_id=job.id,
                level="success",
            )
            return {"ok": True, "next": "outsource"}

        # inhouse 推奨 (またはタイプ未設定) は execute へ
        log_event(
            "pipeline",
            "GOサイン受領",
            f"'{job.title[:30]}' → 制作開始",
            job_id=job.id,
            level="success",
        )
        await _execute(db, job)
        return {"ok": True, "next": "inhouse_executed"}
    finally:
        db.close()


def skip_job(job_id: int) -> dict:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"ok": False, "error": "案件が見つかりません"}
        job.status = JobStatus.SKIPPED
        db.commit()
        log_event(
            "pipeline",
            "見送り",
            f"'{job.title[:30]}' → SKIPPED",
            job_id=job.id,
            level="warn",
        )
        return {"ok": True}
    finally:
        db.close()
