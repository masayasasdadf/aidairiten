"""
使い方:
  python main.py          # ダッシュボード起動 + スケジューラ
  python main.py --once   # パイプラインを1回だけ実行して終了
"""

import asyncio
import argparse
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from db.database import init_db
from config import settings
from pipeline import run_pipeline


def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_pipeline,
        trigger="interval",
        minutes=settings.monitor_interval_minutes,
        id="pipeline",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="パイプラインを1回だけ実行")
    args = parser.parse_args()

    init_db()

    if args.once:
        await run_pipeline()
        return

    # スケジューラ起動（初回すぐ実行）
    scheduler = start_scheduler()
    asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(run_pipeline()))

    # ダッシュボード起動
    from dashboard.app import app
    config = uvicorn.Config(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    print(f"ダッシュボード起動: http://localhost:{settings.dashboard_port}")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
