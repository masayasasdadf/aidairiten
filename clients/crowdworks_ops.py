"""CrowdWorks にログインして応募・メッセージ送受信を行う Playwright クライアント。

セレクタは現行 DOM を当てに行く。失敗時は活動ログに詳細を残し、
呼び出し側が判断できるよう例外ではなく結果 dict を返す。
"""

import asyncio
import re
from datetime import datetime
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Page,
    BrowserContext,
    TimeoutError as PlaywrightTimeout,
)

from dashboard.events import log_event
from db.credentials import get_credential

LOGIN_URL = "https://crowdworks.jp/login"
INBOX_URL = "https://crowdworks.jp/notifications"  # 通知/メッセージ一覧
MESSAGES_URL = "https://crowdworks.jp/messages"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--no-zygote",
    "--disable-background-networking",
]


class CrowdworksOps:
    """ブラウザを1つ立ち上げて、複数操作を同じセッションで行うラッパ。"""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._logged_in = False

    async def __aenter__(self) -> "CrowdworksOps":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        self._context = await self._browser.new_context(user_agent=USER_AGENT, locale="ja-JP")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
        finally:
            if self._pw:
                await self._pw.stop()

    async def login(self) -> bool:
        if self._logged_in:
            return True
        email = get_credential("crowdworks_email")
        password = get_credential("crowdworks_password")
        if not email or not password:
            log_event("ops", "crowdworks", "認証情報未設定のためログイン不可", level="error")
            return False

        page = await self._context.new_page()
        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            email_candidates = [
                'input[name="username"]',
                'input[name="username_or_email"]',
                'input[name="email"]',
                'input#username',
                'input#email',
                'input[type="email"]',
            ]
            pass_candidates = [
                'input[name="password"]',
                'input#password',
                'input[type="password"]',
            ]

            email_sel = await self._first_visible(page, email_candidates, timeout=15000)
            if not email_sel:
                body_text = (await page.inner_text("body"))[:200].replace("\n", " ")
                log_event(
                    "ops",
                    "crowdworks",
                    f"ログインフォーム検出失敗 (URL={page.url}) body: {body_text}",
                    level="error",
                )
                return False
            pass_sel = await self._first_visible(page, pass_candidates, timeout=2000)
            if not pass_sel:
                log_event("ops", "crowdworks", "パスワード欄未検出", level="error")
                return False

            await page.fill(email_sel, email)
            await page.fill(pass_sel, password)
            await page.press(pass_sel, "Enter")

            try:
                await page.wait_for_url(
                    lambda url: "/login" not in url and "/sign_in" not in url,
                    timeout=20000,
                )
            except PlaywrightTimeout:
                body_snippet = ""
                try:
                    body_snippet = (await page.inner_text("body"))[:200].replace("\n", " ")
                except Exception:
                    pass
                log_event(
                    "ops",
                    "crowdworks",
                    f"ログイン後の遷移なし (URL={page.url}) body: {body_snippet}",
                    level="error",
                )
                return False

            log_event("ops", "crowdworks", f"ログイン成功 (URL={page.url})", level="success")
            self._logged_in = True
            return True
        finally:
            await page.close()

    async def submit_application(
        self,
        job_url: str,
        proposal_text: str,
        proposed_amount: Optional[int] = None,
        proposed_days: Optional[int] = None,
    ) -> dict:
        """案件詳細 → 応募ボタン → フォーム → 送信。

        セレクタは現行 DOM ベースで複数候補を試行。失敗時は理由を返す。
        """

        if not await self.login():
            return {"ok": False, "error": "ログイン失敗"}

        page = await self._context.new_page()
        try:
            log_event("ops", "crowdworks", f"案件詳細を開く: {job_url}")
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # 「応募する」「提案する」ボタン候補
            apply_btn_candidates = [
                'a:has-text("応募する")',
                'a:has-text("提案する")',
                'button:has-text("応募する")',
                'button:has-text("提案する")',
                'a[href*="/proposal"]',
                'a[href*="/applications/new"]',
            ]
            apply_btn = await self._first_visible(page, apply_btn_candidates, timeout=10000)
            if not apply_btn:
                snippet = (await page.inner_text("body"))[:200].replace("\n", " ")
                log_event("ops", "crowdworks", f"応募ボタン未検出: {snippet}", level="error")
                return {"ok": False, "error": "応募ボタンが見つからない"}

            await page.locator(apply_btn).first.click()
            await page.wait_for_load_state("domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # 応募フォーム
            msg_field_candidates = [
                'textarea[name*="message"]',
                'textarea[name*="proposal"]',
                'textarea[name*="application"]',
                'textarea',
            ]
            msg_sel = await self._first_visible(page, msg_field_candidates, timeout=10000)
            if not msg_sel:
                log_event("ops", "crowdworks", "提案文入力欄未検出", level="error")
                return {"ok": False, "error": "提案文入力欄が見つからない"}
            await page.fill(msg_sel, proposal_text)

            # 金額・納期 (任意。フィールド無くてもエラーにしない)
            if proposed_amount:
                amt_sel = await self._first_visible(page, [
                    'input[name*="amount"]',
                    'input[name*="price"]',
                    'input[name*="budget"]',
                ], timeout=2000)
                if amt_sel:
                    try:
                        await page.fill(amt_sel, str(proposed_amount))
                    except Exception:
                        pass
            if proposed_days:
                days_sel = await self._first_visible(page, [
                    'input[name*="days"]',
                    'input[name*="period"]',
                    'input[name*="delivery"]',
                ], timeout=2000)
                if days_sel:
                    try:
                        await page.fill(days_sel, str(proposed_days))
                    except Exception:
                        pass

            # 送信
            submit_candidates = [
                'button[type="submit"]:has-text("送信")',
                'button[type="submit"]:has-text("応募")',
                'button[type="submit"]:has-text("提案")',
                'button[type="submit"]',
                'input[type="submit"]',
            ]
            submit_sel = await self._first_visible(page, submit_candidates, timeout=5000)
            if not submit_sel:
                log_event("ops", "crowdworks", "送信ボタン未検出", level="error")
                return {"ok": False, "error": "送信ボタンが見つからない"}

            await page.locator(submit_sel).first.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=20000)
            except PlaywrightTimeout:
                pass
            await asyncio.sleep(2)

            # 送信完了の判定: URL に /complete or /thanks or /done が入る、または成功メッセージ
            ok_text_check = False
            try:
                body = (await page.inner_text("body"))[:500]
                if any(k in body for k in ["応募が完了", "提案が完了", "応募ありがとう", "送信しました"]):
                    ok_text_check = True
            except Exception:
                pass

            if ok_text_check or any(k in page.url for k in ["complete", "thanks", "done"]):
                log_event("ops", "crowdworks", f"応募送信成功 (URL={page.url})", level="success")
                return {"ok": True, "final_url": page.url}

            log_event(
                "ops",
                "crowdworks",
                f"応募送信後の確認文言なし (URL={page.url}) — 送信されたか不明",
                level="warn",
            )
            return {"ok": True, "final_url": page.url, "warning": "送信完了の確証なし"}

        except Exception as e:
            log_event("ops", "crowdworks", f"応募例外: {e}", level="error")
            return {"ok": False, "error": str(e)}
        finally:
            await page.close()

    async def fetch_inbox_threads(self) -> list[dict]:
        """メッセージ受信箱を巡回し、各スレッドの (job, sender, last_message) を返す。"""

        if not await self.login():
            return []

        page = await self._context.new_page()
        try:
            log_event("ops", "crowdworks", "受信箱を確認")
            await page.goto(MESSAGES_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            threads = await page.evaluate(
                """
                () => {
                    const out = [];
                    // メッセージスレッドへのリンクっぽいものを総当たりで拾う
                    document.querySelectorAll('a[href*="/messages/"]').forEach(a => {
                        const m = a.href.match(/\\/messages\\/(\\d+)/);
                        if (!m) return;
                        const id = m[1];
                        const card = a.closest('li, article, tr') || a.parentElement;
                        const text = card ? card.textContent.trim() : '';
                        out.push({ thread_id: id, url: a.href, snippet: text.slice(0, 200) });
                    });
                    // 重複排除
                    const seen = new Set();
                    return out.filter(x => {
                        if (seen.has(x.thread_id)) return false;
                        seen.add(x.thread_id);
                        return true;
                    });
                }
                """
            )
            log_event("ops", "crowdworks", f"受信箱スレッド {len(threads)} 件")
            return threads
        except Exception as e:
            log_event("ops", "crowdworks", f"受信箱例外: {e}", level="error")
            return []
        finally:
            await page.close()

    async def fetch_thread_messages(self, thread_url: str) -> list[dict]:
        """1スレッドの全メッセージを取得 (sender, content, sent_at, external_id)。"""

        if not await self.login():
            return []

        page = await self._context.new_page()
        try:
            await page.goto(thread_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            messages = await page.evaluate(
                """
                () => {
                    // 雑にメッセージっぽいブロックを拾う。サイト側DOMに合わせて要調整。
                    const out = [];
                    document.querySelectorAll('[class*="message"], [class*="Message"], [class*="comment"]').forEach((el, idx) => {
                        const text = (el.textContent || '').trim();
                        if (text.length < 5 || text.length > 5000) return;
                        const isMine = !!el.querySelector('[class*="self"], [class*="mine"], [class*="own"]');
                        out.push({
                            ext_id: el.id || ('m_' + idx),
                            sender: isMine ? 'us' : 'client',
                            content: text,
                        });
                    });
                    return out;
                }
                """
            )
            return messages
        except Exception as e:
            log_event("ops", "crowdworks", f"スレッド取得例外: {e}", level="error")
            return []
        finally:
            await page.close()

    async def send_reply(self, thread_url: str, body: str) -> dict:
        """1スレッドに返信を送る。"""

        if not await self.login():
            return {"ok": False, "error": "ログイン失敗"}

        page = await self._context.new_page()
        try:
            await page.goto(thread_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            input_candidates = [
                'textarea[name*="message"]',
                'textarea[name*="body"]',
                'textarea[name*="content"]',
                'textarea',
            ]
            input_sel = await self._first_visible(page, input_candidates, timeout=10000)
            if not input_sel:
                log_event("ops", "crowdworks", "返信入力欄未検出", level="error")
                return {"ok": False, "error": "入力欄なし"}

            await page.fill(input_sel, body)

            send_candidates = [
                'button[type="submit"]:has-text("送信")',
                'button[type="submit"]',
                'input[type="submit"]',
            ]
            send_sel = await self._first_visible(page, send_candidates, timeout=5000)
            if not send_sel:
                return {"ok": False, "error": "送信ボタンなし"}

            await page.locator(send_sel).first.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightTimeout:
                pass
            log_event("ops", "crowdworks", "返信送信完了", level="success")
            return {"ok": True}
        except Exception as e:
            log_event("ops", "crowdworks", f"返信例外: {e}", level="error")
            return {"ok": False, "error": str(e)}
        finally:
            await page.close()

    @staticmethod
    async def _first_visible(page: Page, candidates: list[str], timeout: int) -> Optional[str]:
        end = asyncio.get_event_loop().time() + (timeout / 1000)
        while asyncio.get_event_loop().time() < end:
            for sel in candidates:
                try:
                    locator = page.locator(sel).first
                    if await locator.count() > 0 and await locator.is_visible():
                        return sel
                except Exception:
                    continue
            await asyncio.sleep(0.4)
        return None
