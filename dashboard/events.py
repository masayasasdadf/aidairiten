"""
社内活動の見える化用イベントバス。
ダッシュボードと同じプロセス内に居るパイプライン/エージェント/スクレイパが
log_event() で発火、UI が /api/activity で取得する。
"""

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

_MAX_EVENTS = 300
_events: deque = deque(maxlen=_MAX_EVENTS)
_lock = Lock()


def log_event(
    actor: str,
    action: str,
    detail: str = "",
    job_id: Optional[int] = None,
    level: str = "info",
) -> None:
    """イベント記録 + Render ログ用に標準出力にも流す。

    actor   : 'scraper' / 'analysis' / 'execution' / 'qc' / 'pipeline' など
    action  : '巡回' / '分析' / '生産' / 'QC' など
    detail  : 自由テキスト（案件タイトルやスコア等）
    level   : 'info' / 'success' / 'warn' / 'error'
    """
    evt = {
        "ts": datetime.now(timezone.utc).isoformat(),
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


def get_events(limit: int = 100) -> list[dict]:
    with _lock:
        snapshot = list(_events)
    return snapshot[-limit:][::-1]
