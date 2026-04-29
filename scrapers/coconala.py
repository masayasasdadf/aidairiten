import re
import asyncio

import httpx
from bs4 import BeautifulSoup

from db.credentials import get_credential
from scrapers.base import BaseScraper, RawJob

# ココナラはサービス出品型なので「依頼（リクエスト）」ボードを監視
SEARCH_URLS = [
    "https://coconala.com/requests/categories/101",   # ライティング・翻訳
    "https://coconala.com/requests/categories/201",   # Web制作
    "https://coconala.com/requests/categories/401",   # データ入力
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ja,en;q=0.9",
}


class CoconalaScraper(BaseScraper):
    platform_name = "coconala"

    async def fetch_jobs(self) -> list[RawJob]:
        if not get_credential("coconala_email") or not get_credential("coconala_password"):
            print("[Coconala] 認証情報未設定のためスキップ")
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
                    print(f"[Coconala] fetch error {url}: {e}")
        return jobs

    def _parse_list(self, html: str) -> list[RawJob]:
        soup = BeautifulSoup(html, "lxml")
        results = []

        for item in soup.select(".p-request-list__item, .request-item, [class*='RequestCard']"):
            try:
                title_el = item.select_one("h2 a, h3 a, .request-title a")
                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                if not href.startswith("http"):
                    href = "https://coconala.com" + href

                job_id = re.search(r"/requests/(\d+)", href)
                external_id = f"co_{job_id.group(1)}" if job_id else f"co_{hash(href)}"

                desc_el = item.select_one(".request-description, .p-request__body")
                description = desc_el.get_text(strip=True) if desc_el else ""

                price_el = item.select_one(".request-budget, .p-request__budget")
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
