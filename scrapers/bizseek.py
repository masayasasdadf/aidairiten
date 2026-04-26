import re
import asyncio

import httpx
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, RawJob

SEARCH_URLS = [
    "https://www.bizseek.jp/project/?category=wr&sort=new",   # ライティング
    "https://www.bizseek.jp/project/?category=web&sort=new",  # Web制作
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


class BizseekScraper(BaseScraper):
    platform_name = "bizseek"

    async def fetch_jobs(self) -> list[RawJob]:
        jobs = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            for url in SEARCH_URLS:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    jobs.extend(self._parse_list(resp.text))
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"[Bizseek] fetch error {url}: {e}")
        return jobs

    def _parse_list(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for item in soup.select(".project-item, .job-list__item"):
            try:
                title_el = item.select_one("h3 a, .project-title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.bizseek.jp" + href

                job_id = re.search(r"/project/(\d+)", href)
                external_id = f"bz_{job_id.group(1)}" if job_id else f"bz_{hash(href)}"

                desc_el = item.select_one(".project-description")
                description = desc_el.get_text(strip=True) if desc_el else ""

                price_el = item.select_one(".project-price, .budget")
                price_text = price_el.get_text(strip=True) if price_el else ""
                price = self._parse_price(price_text)

                results.append(RawJob(
                    platform=self.platform_name,
                    external_id=external_id,
                    url=href,
                    title=title,
                    description=description,
                    price_fixed=price,
                ))
            except Exception:
                continue

        return results
