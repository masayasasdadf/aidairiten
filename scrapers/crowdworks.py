import re
import asyncio
from datetime import datetime
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper, RawJob

SEARCH_URLS = [
    "https://crowdworks.jp/public/jobs/search?job_type=writing&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=web_creation&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=translation&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=data_entry&order=new",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


class CrowdworksScraper(BaseScraper):
    platform_name = "crowdworks"

    async def fetch_jobs(self) -> list[RawJob]:
        jobs = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            for url in SEARCH_URLS:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    jobs.extend(self._parse_list(resp.text, url))
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"[CrowdWorks] fetch error {url}: {e}")
        return jobs

    def _parse_list(self, html: str, base_url: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for item in soup.select("li.job_offer__item, article.job-item"):
            try:
                title_el = item.select_one("h3 a, .job-item__title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not href.startswith("http"):
                    href = "https://crowdworks.jp" + href

                job_id = re.search(r"/jobs/(\d+)", href)
                external_id = f"cw_{job_id.group(1)}" if job_id else f"cw_{hash(href)}"

                desc_el = item.select_one(".job_offer__description, .job-item__description")
                description = desc_el.get_text(strip=True) if desc_el else ""

                price_el = item.select_one(".job_offer__price, .job-item__price")
                price_text = price_el.get_text(strip=True) if price_el else ""
                price = self._parse_price(price_text)

                client_el = item.select_one(".job_offer__client, .job-item__client")
                client_name = client_el.get_text(strip=True) if client_el else ""

                results.append(RawJob(
                    platform=self.platform_name,
                    external_id=external_id,
                    url=href,
                    title=title,
                    description=description,
                    price_fixed=price,
                    client_name=client_name,
                ))
            except Exception:
                continue

        return results
