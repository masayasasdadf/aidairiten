import re
import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

from config import settings
from dashboard.events import log_event
from scrapers.base import BaseScraper, RawJob

LOGIN_URL = "https://crowdworks.jp/login"

# ログイン後にアクセスする検索ページ
SEARCH_URLS = [
    "https://crowdworks.jp/public/jobs/search?job_type=writing&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=web_creation&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=translation&order=new",
    "https://crowdworks.jp/public/jobs/search?job_type=data_entry&order=new",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class CrowdworksScraper(BaseScraper):
    platform_name = "crowdworks"

    async def fetch_jobs(self) -> list[RawJob]:
        if not settings.crowdworks_email or not settings.crowdworks_password:
            log_event("scraper", "crowdworks", "認証情報未設定のためスキップ", level="warn")
            return []

        log_event("scraper", "crowdworks", "巡回開始")

        jobs: list[RawJob] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(user_agent=USER_AGENT, locale="ja-JP")
            page = await context.new_page()
            try:
                logged_in = await self._login(page)
                if not logged_in:
                    return []

                for url in SEARCH_URLS:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_load_state("networkidle", timeout=15000)
                        items = await self._parse_list(page)
                        log_event("scraper", "crowdworks", f"{url} → {len(items)}件")
                        jobs.extend(items)
                        await asyncio.sleep(2)
                    except PlaywrightTimeout:
                        log_event("scraper", "crowdworks", f"timeout {url}", level="warn")
                    except Exception as e:
                        log_event("scraper", "crowdworks", f"fetch error {url}: {e}", level="error")
            finally:
                await context.close()
                await browser.close()

        # 重複排除（複数カテゴリで同じ案件が出ることがある）
        dedup: dict[str, RawJob] = {}
        for j in jobs:
            dedup[j.external_id] = j
        return list(dedup.values())

    async def _login(self, page: Page) -> bool:
        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            # ログインフォームのセレクタ候補（DOM変更に備えて複数試行）
            email_sel = 'input[name="username"], input[type="email"], input#username, input[name="email"]'
            pass_sel = 'input[name="password"], input[type="password"], input#password'
            submit_sel = 'button[type="submit"], input[type="submit"]'

            await page.wait_for_selector(email_sel, timeout=10000)
            await page.fill(email_sel, settings.crowdworks_email)
            await page.fill(pass_sel, settings.crowdworks_password)
            await page.click(submit_sel)
            await page.wait_for_load_state("networkidle", timeout=20000)

            # ログイン成否判定: URL に /login が残ってたら失敗
            if "/login" in page.url:
                log_event(
                    "scraper",
                    "crowdworks",
                    f"ログイン失敗: 認証情報が無効またはCAPTCHA要求 (URL={page.url})",
                    level="error",
                )
                return False

            log_event("scraper", "crowdworks", f"ログイン成功 (URL={page.url})", level="success")
            return True
        except PlaywrightTimeout:
            log_event("scraper", "crowdworks", f"ログインタイムアウト (URL={page.url})", level="error")
            return False
        except Exception as e:
            log_event("scraper", "crowdworks", f"ログイン例外: {e}", level="error")
            return False

    async def _parse_list(self, page: Page) -> list[RawJob]:
        # JS で全リンクを走査して案件 ID 単位にユニーク化、カードのテキストも吸い出す
        items = await page.evaluate(
            """
            () => {
                const out = [];
                const seen = new Set();
                document.querySelectorAll('a[href*="/public/jobs/"]').forEach(a => {
                    const m = a.href.match(/\\/public\\/jobs\\/(\\d+)/);
                    if (!m) return;
                    const id = m[1];
                    if (seen.has(id)) return;
                    const title = (a.textContent || '').trim();
                    if (!title) return;
                    seen.add(id);
                    let card = a.closest('li, article');
                    if (!card) card = a.parentElement;
                    const cardText = card ? (card.textContent || '').trim() : '';
                    out.push({ id, url: a.href, title, cardText });
                });
                return out;
            }
            """
        )

        results: list[RawJob] = []
        for it in items:
            card_text: str = it.get("cardText", "")
            title: str = it.get("title", "")
            description = card_text.replace(title, "").strip()[:500]
            price = self._extract_price(card_text)
            results.append(
                RawJob(
                    platform=self.platform_name,
                    external_id=f"cw_{it['id']}",
                    url=it["url"],
                    title=title,
                    description=description,
                    price_fixed=price,
                )
            )
        return results

    def _extract_price(self, text: str) -> Optional[int]:
        # "10,000円" のような最初に出る金額表記を拾う
        m = re.search(r"([\d,]+)\s*円", text)
        if not m:
            return None
        digits = m.group(1).replace(",", "")
        return int(digits) if digits.isdigit() else None
