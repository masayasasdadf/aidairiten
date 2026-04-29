"""DeepSeek 互換 OpenAI クライアントの生成ヘルパ。

API キーは UI 経由で更新できるため、各呼び出しで都度 DB から取り直す。
クライアント生成は軽量なのでキャッシュしない。
"""

from openai import OpenAI

from db.credentials import get_credential


def get_client() -> OpenAI:
    api_key = get_credential("deepseek_api_key") or "missing"
    base_url = get_credential("deepseek_base_url") or "https://api.deepseek.com"
    return OpenAI(api_key=api_key, base_url=base_url)
