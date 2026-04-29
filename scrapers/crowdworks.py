import re
import os
import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

from dashboard.events import log_event
from db.credentials import get_credential
from scrapers.base import BaseScraper, RawJob

LOGIN_URL = "https://crowdworks.jp/login"

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

# 並列営業マンの人数。Render Free 512MB では 1 が安全。
# Standard 以上に上げたら env で SCRAPER_WORKERS=2〜4 に増やす
PARALLEL_WORKERS = int(os.environ.get("SCRAPER_WORKERS", "1"))

# Free tier OOM 対策 + コンテナ環境向けの Chromium 省メモリフラグ
CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",  # /tmp を使う (Render の /dev/shm は小さい)
    "--disable-gpu",
    "--disable-extensions",
    "--no-zygote",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-sync",
    "--mute-audio",
]


class CrowdworksScraper(BaseScraper):
    platform_name = "crowdworks"

    async def fetch_jobs(self) -> list[RawJob]:
        email = get_credential("crowdworks_email")
        password = get_credential("crowdworks_password")

        log_event("scraper", "crowdworks", "巡回開始")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
            context = await browser.new_context(user_agent=USER_AGENT, locale="ja-JP")
            try:
                logged_in = False
                if email and password:
                    page = await context.new_page()
                    try:
                        logged_in = await self._login(page, email, password)
                    finally:
                        await page.close()
                    if not logged_in:
                        log_event(
                            "scraper",
                            "crowdworks",
                            "ログイン失敗 → 公開ページで巡回続行",
                            level="warn",
                        )
                else:
                    log_event(
                        "scraper",
                        "crowdworks",
                        "認証情報未設定 → 公開ページで巡回",
                        level="warn",
                    )

                jobs = await self._scrape_urls_parallel(context, SEARCH_URLS, public=not logged_in)
            finally:
                await context.close()
                await browser.close()

        dedup: dict[str, RawJob] = {}
        for j in jobs:
            dedup[j.external_id] = j
        return list(dedup.values())

    async def _scrape_urls_parallel(
        self, context: BrowserContext, urls: list[str], public: bool
    ) -> list[RawJob]:
        """営業マン PARALLEL_WORKERS 人で URL を分担巡回。"""

        sem = asyncio.Semaphore(PARALLEL_WORKERS)
        prefix = "(公開) " if public else ""

        async def scrape_one(url: str) -> list[RawJob]:
            async with sem:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    try:
                        await page.wait_for_selector('a[href*="/public/jobs/"]', timeout=10000)
                    except PlaywrightTimeout:
                        pass
                    await asyncio.sleep(1)
                    items = await self._parse_list(page)
                    log_event("scraper", "crowdworks", f"{prefix}{url} → {len(items)}件")
                    return items
                except PlaywrightTimeout:
                    log_event("scraper", "crowdworks", f"{prefix}timeout {url}", level="warn")
                    return []
                except Exception as e:
                    log_event("scraper", "crowdworks", f"{prefix}fetch error {url}: {e}", level="error")
                    return []
                finally:
                    await page.close()

        results = await asyncio.gather(*[scrape_one(u) for u in urls])
        return [j for sub in results for j in sub]

    async def _login(self, page: Page, email: str, password: str) -> bool:
        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            log_event("scraper", "crowdworks", "ログインページ読み込みタイムアウト", level="error")
            return False

        title = await page.title()
        log_event("scraper", "crowdworks", f"ログインページ到達 (title={title!r})")

        # CrowdWorks の現行ログインフォームに合わせたセレクタを優先
        email_candidates = [
            'input[name="username"]',
            'input[name="username_or_email"]',
            'input[name="email"]',
            'input#username',
            'input#email',
            'input[type="email"]',
            'input[type="text"][autocomplete*="email"]',
            'input[type="text"][autocomplete*="username"]',
        ]
        pass_candidates = [
            'input[name="password"]',
            'input#password',
            'input[type="password"]',
        ]

        email_sel = await self._first_visible(page, email_candidates, timeout=15000)
        if not email_sel:
            try:
                body_text = (await page.inner_text("body"))[:300].replace("\n", " ")
            except Exception:
                body_text = ""
            log_event(
                "scraper",
                "crowdworks",
                f"ログインフォーム検出失敗 (URL={page.url}, title={title!r}) body先頭: {body_text}",
                level="error",
            )
            return False

        pass_sel = await self._first_visible(page, pass_candidates, timeout=2000)
        if not pass_sel:
            log_event("scraper", "crowdworks", "パスワード欄が見つからず", level="error")
            return False

        try:
            await page.fill(email_sel, email)
            await page.fill(pass_sel, password)
            await page.press(pass_sel, "Enter")
        except Exception as e:
            log_event("scraper", "crowdworks", f"フォーム入力例外: {e}", level="error")
            return False

        try:
            await page.wait_for_url(
                lambda url: "/login" not in url and "/sign_in" not in url,
                timeout=20000,
            )
        except PlaywrightTimeout:
            try:
                body_snippet = (await page.inner_text("body"))[:200].replace("\n", " ")
            except Exception:
                body_snippet = ""
            log_event(
                "scraper",
                "crowdworks",
                f"ログイン後の遷移なし (URL={page.url}) body先頭: {body_snippet}",
                level="error",
            )
            return False

        log_event("scraper", "crowdworks", f"ログイン成功 (URL={page.url})", level="success")
        return True

    @staticmethod
    async def _first_visible(page: Page, candidates: list[str], timeout: int) -> Optional[str]:
        """候補セレクタを順に試して、可視で存在する最初のものを返す。"""

        end = asyncio.get_event_loop().time() + (timeout / 1000)
        # 最初の数秒は描画待ち。その後は即チェックで諦める
        while asyncio.get_event_loop().time() < end:
            for sel in candidates:
                try:
                    locator = page.locator(sel).first
                    if await locator.count() > 0 and await locator.is_visible():
                        return sel
                except Exception:
                    continue
            await asyncio.sleep(0.5)
        return None

    async def _parse_list(self, page: Page) -> list[RawJob]:
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
        m = re.search(r"([\d,]+)\s*円", text)
        if not m:
            return None
        digits = m.group(1).replace(",", "")
        return int(digits) if digits.isdigit() else None
