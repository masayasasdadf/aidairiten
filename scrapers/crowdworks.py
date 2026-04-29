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
            log_event("scraper", "crowdworks", "認証情報未設定 → 公開ページで巡回", level="warn")
            return await self._fetch_public()

        log_event("scraper", "crowdworks", "巡回開始")

        jobs: list[RawJob] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(user_agent=USER_AGENT, locale="ja-JP")
            page = await context.new_page()
            try:
                logged_in = await self._login(page)
                if not logged_in:
                    log_event(
                        "scraper",
                        "crowdworks",
                        "ログイン失敗 → 公開ページで巡回続行",
                        level="warn",
                    )

                for url in SEARCH_URLS:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        # SPA 描画待ち: 案件カードのリンクがDOMに出るまで最大10秒
                        try:
                            await page.wait_for_selector(
                                'a[href*="/public/jobs/"]', timeout=10000
                            )
                        except PlaywrightTimeout:
                            pass
                        await asyncio.sleep(1)
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

    async def _fetch_public(self) -> list[RawJob]:
        """ログイン無しで公開検索ページを巡回（フォールバック）。"""

        jobs: list[RawJob] = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(user_agent=USER_AGENT, locale="ja-JP")
            page = await context.new_page()
            try:
                for url in SEARCH_URLS:
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        try:
                            await page.wait_for_selector('a[href*="/public/jobs/"]', timeout=10000)
                        except PlaywrightTimeout:
                            pass
                        await asyncio.sleep(1)
                        items = await self._parse_list(page)
                        log_event("scraper", "crowdworks", f"(公開) {url} → {len(items)}件")
                        jobs.extend(items)
                        await asyncio.sleep(2)
                    except Exception as e:
                        log_event("scraper", "crowdworks", f"(公開) fetch error {url}: {e}", level="error")
            finally:
                await context.close()
                await browser.close()
        dedup: dict[str, RawJob] = {}
        for j in jobs:
            dedup[j.external_id] = j
        return list(dedup.values())

    async def _login(self, page: Page) -> bool:
        # Step 1: ログインページを開く
        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            log_event("scraper", "crowdworks", "ログインページ読み込みタイムアウト", level="error")
            return False

        title = await page.title()
        log_event("scraper", "crowdworks", f"ログインページ到達 (title={title!r})")

        # Step 2: メール欄を待つ
        email_sel = 'input[name="username"], input[name="email"], input[type="email"], input#username, input#email'
        pass_sel = 'input[name="password"], input[type="password"], input#password'
        try:
            await page.wait_for_selector(email_sel, timeout=15000, state="visible")
        except PlaywrightTimeout:
            log_event(
                "scraper",
                "crowdworks",
                f"ログインフォーム検出失敗 (URL={page.url}, title={title!r})",
                level="error",
            )
            return False

        # Step 3: 入力 → Enter で送信（ボタンセレクタの揺れを回避）
        try:
            await page.fill(email_sel, settings.crowdworks_email)
            await page.fill(pass_sel, settings.crowdworks_password)
            await page.press(pass_sel, "Enter")
        except Exception as e:
            log_event("scraper", "crowdworks", f"フォーム入力例外: {e}", level="error")
            return False

        # Step 4: /login から遷移するのを待つ。networkidle は GA 等で永遠に来ないので使わない
        try:
            await page.wait_for_url(
                lambda url: "/login" not in url and "/sign_in" not in url,
                timeout=20000,
            )
        except PlaywrightTimeout:
            # /login に留まっている = 認証失敗 or CAPTCHA
            body_snippet = ""
            try:
                body_snippet = (await page.inner_text("body"))[:200].replace("\n", " ")
            except Exception:
                pass
            log_event(
                "scraper",
                "crowdworks",
                f"ログイン後の遷移なし (URL={page.url}) body先頭: {body_snippet}",
                level="error",
            )
            return False

        log_event("scraper", "crowdworks", f"ログイン成功 (URL={page.url})", level="success")
        return True

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
