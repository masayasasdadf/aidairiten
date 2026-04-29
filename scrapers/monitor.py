import asyncio

from scrapers.base import RawJob
from scrapers.crowdworks import CrowdworksScraper
from scrapers.lancers import LancersScraper
from scrapers.coconala import CoconalaScraper

ALL_SCRAPERS = [
    CrowdworksScraper,
    LancersScraper,
    CoconalaScraper,
]


async def run_all_scrapers() -> list[RawJob]:
    tasks = [scraper().fetch_jobs() for scraper in ALL_SCRAPERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    jobs = []
    for scraper_cls, result in zip(ALL_SCRAPERS, results):
        if isinstance(result, Exception):
            print(f"[Monitor] {scraper_cls.platform_name} failed: {result}")
        else:
            print(f"[Monitor] {scraper_cls.platform_name}: {len(result)} jobs found")
            jobs.extend(result)

    return jobs
