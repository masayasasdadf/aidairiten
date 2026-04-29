import re
import asyncio

import httpx
from bs4 import BeautifulSoup

from config import settings
from scrapers.base import BaseScraper, RawJob

SEARCH_URLS = [
    "https://www.lancers.jp/work/search?type=1&sort=new",   # 執筆・ライティング
    "https://www.lancers.jp/work/search?type=2&sort=new",   # Webデザイン
    "https://www.lancers.jp/work/search?type=6&sort=new",   # 翻訳
    "https://www.lancers.jp/work/search?type=8&sort=new",   # データ入力
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


class LancersScraper(BaseScraper):
    platform_name = "lancers"

    async def fetch_jobs(self) -> list[RawJob]:
        if not settings.lancers_email or not settings.lancers_password:
            print("[Lancers] 認証情報未設定のためスキップ")
            return []

        jobs = []
        async with httpx.AsyncClient(headers=HEADERS, timeout=30, follow_redirects=True) as client:
            for url in SEARCH_URLS:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    jobs.extend(self._parse_list(resp.text))
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"[Lancers] fetch error {url}: {e}")
        return jobs

    def _parse_list(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for item in soup.select(".p-workItem, .work-item, li[class*='work']"):
            try:
                title_el = item.select_one("h3 a, .p-workItem__title a, .work-title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not href.startswith("http"):
                    href = "https://www.lancers.jp" + href

                job_id = re.search(r"/work/detail/(\d+)", href)
                external_id = f"la_{job_id.group(1)}" if job_id else f"la_{hash(href)}"

                desc_el = item.select_one(".p-workItem__description, .work-description")
                description = desc_el.get_text(strip=True) if desc_el else ""

                price_el = item.select_one(".p-workItem__budget, .work-budget, .price")
                price_text = price_el.get_text(strip=True) if price_el else ""

                price_min, price_max = self._parse_range(price_text)

                client_el = item.select_one(".p-workItem__client, .work-client")
                client_name = client_el.get_text(strip=True) if client_el else ""

                results.append(RawJob(
                    platform=self.platform_name,
                    external_id=external_id,
                    url=href,
                    title=title,
                    description=description,
                    price_min=price_min,
                    price_max=price_max,
                    client_name=client_name,
                ))
            except Exception:
                continue

        return results

    def _parse_range(self, text: str) -> tuple[int | None, int | None]:
        nums = re.findall(r"[\d,]+", text)
        prices = [int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit()]
        if len(prices) >= 2:
            return prices[0], prices[1]
        elif len(prices) == 1:
            return prices[0], None
        return None, None
