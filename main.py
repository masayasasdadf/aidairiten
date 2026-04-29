"""
使い方:
  python main.py          # ダッシュボード起動。巡回はUIから手動トリガ
  python main.py --once   # 巡回を1回だけ実行して終了（CLI用途）
"""

import asyncio
import argparse
import os

import uvicorn

from config import settings
from db.database import init_db
from pipeline import run_pipeline


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="巡回を1回だけ実行して終了")
    args = parser.parse_args()

    init_db()

    if args.once:
        await run_pipeline()
        return

    from dashboard.app import app

    port = int(os.environ.get("PORT", settings.dashboard_port))
    config = uvicorn.Config(app, host=settings.dashboard_host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    print(f"ダッシュボード起動: http://{settings.dashboard_host}:{port}（巡回はUIから手動トリガ）")
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
