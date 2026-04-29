"""社内活動の見える化用イベントバス。

DB 永続化 + プロセス内 deque キャッシュのハイブリッド。
コールドスタート時は DB から最新300件を deque に復元する。
"""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

_MAX_EVENTS = 300
_events: deque = deque(maxlen=_MAX_EVENTS)
_lock = Lock()
_restored = False


def _restore_from_db_if_needed() -> None:
    global _restored
    if _restored:
        return
    _restored = True
    try:
        from db.database import SessionLocal
        from db.models import EventLog

        db = SessionLocal()
        try:
            rows = (
                db.query(EventLog)
                .order_by(EventLog.id.desc())
                .limit(_MAX_EVENTS)
                .all()
            )
            rows.reverse()
            with _lock:
                for r in rows:
                    _events.append({
                        "ts": (r.ts or datetime.utcnow()).replace(tzinfo=timezone.utc).isoformat(),
                        "actor": r.actor,
                        "action": r.action,
                        "detail": r.detail or "",
                        "job_id": r.job_id,
                        "level": r.level or "info",
                    })
        finally:
            db.close()
    except Exception as e:
        # DB が初期化前など。次回呼び出し時に再試行できるよう _restored を戻す
        _restored = False
        print(f"[events] restore failed: {e}", flush=True)


def log_event(
    actor: str,
    action: str,
    detail: str = "",
    job_id: Optional[int] = None,
    level: str = "info",
) -> None:
    _restore_from_db_if_needed()

    now = datetime.now(timezone.utc)
    evt = {
        "ts": now.isoformat(),
        "actor": actor,
        "action": action,
        "detail": detail,
        "job_id": job_id,
        "level": level,
    }
    with _lock:
        _events.append(evt)

    suffix = f" #{job_id}" if job_id else ""
    print(f"[{actor}] {action} {detail}{suffix}", flush=True)

    # DB 永続化（失敗してもプロセス内ログは残るので握りつぶす）
    try:
        from db.database import SessionLocal
        from db.models import EventLog

        db = SessionLocal()
        try:
            db.add(EventLog(
                actor=actor, action=action, detail=detail,
                job_id=job_id, level=level, ts=now.replace(tzinfo=None),
            ))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        print(f"[events] persist failed: {e}", flush=True)


def get_events(limit: int = 200) -> list[dict]:
    _restore_from_db_if_needed()
    with _lock:
        snapshot = list(_events)
    return snapshot[-limit:][::-1]
