"""業務停止/再開などのシステム制御フラグ。"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from db.database import SessionLocal
from db.models import SystemControl


def _get_or_create(db) -> SystemControl:
    row = db.query(SystemControl).filter(SystemControl.id == 1).first()
    if not row:
        row = SystemControl(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_state() -> dict:
    db = SessionLocal()
    try:
        row = _get_or_create(db)
        now = datetime.utcnow()
        paused = bool(row.paused_until and row.paused_until > now)
        return {
            "paused": paused,
            "paused_until": row.paused_until.isoformat() + "Z" if row.paused_until else None,
            "pause_reason": row.pause_reason,
        }
    finally:
        db.close()


def is_paused() -> tuple[bool, Optional[datetime], Optional[str]]:
    db = SessionLocal()
    try:
        row = _get_or_create(db)
        now = datetime.utcnow()
        if row.paused_until and row.paused_until > now:
            return True, row.paused_until, row.pause_reason
        return False, None, None
    finally:
        db.close()


def pause(hours: float, reason: str) -> datetime:
    until = datetime.utcnow() + timedelta(hours=hours)
    db = SessionLocal()
    try:
        row = _get_or_create(db)
        row.paused_until = until
        row.pause_reason = reason
        db.commit()
        return until
    finally:
        db.close()


def resume() -> None:
    db = SessionLocal()
    try:
        row = _get_or_create(db)
        row.paused_until = None
        row.pause_reason = None
        db.commit()
    finally:
        db.close()
