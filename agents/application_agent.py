"""応募文 (proposal) を起案する LLM エージェント。

クライアントの心に刺さる提案文 + 適正な提案金額・納期を JSON で返す。
"""

import json
import re

from agents.directives import inject as inject_directives
from agents.llm import get_client
from db.models import Job

SYSTEM_PROMPT = """あなたはAI総合商社の営業マネージャーです。
クラウドソーシング案件への応募文（提案文）を起案します。

## 応募文の鉄則
- 結論ファースト: 冒頭で「自分が最適な理由」を1〜2行で
- クライアントの要件に対する具体的な解決策を提示
- 過度な敬語・テンプレ感は避け、誠実かつビジネスライク
- 自社が AI を活用することは正直に明記（隠蔽しない）
- 文字数: 300〜600字程度。読みやすく、改行で構造化
- 押し売り・煽り・誇張は禁止

## 金額/納期の判断
- proposed_amount: 案件側に金額表記があればそれに沿う。記載がなければ
  業界相場（記事 3,000〜10,000 / LP 30,000〜80,000 / 翻訳 字数次第）から提案
- proposed_days: 内容の重さから余裕ある納期を提示（無理しない）"""

USER_PROMPT_TEMPLATE = """以下の案件に応募する提案文を起案してください。

## 案件情報
タイトル: {title}
説明: {description}
プラットフォーム: {platform}
カテゴリ: {category}
分析メモ: {analysis_notes}
価格表記: {price}

## 出力形式 (JSON のみ、他の文字は一切含めない)
{{
  "proposal_text": "ここに提案文（300〜600字、改行を含む）",
  "proposed_amount": <整数 円。不明なら null>,
  "proposed_days": <整数 日数。不明なら null>
}}"""


def _format_price(job: Job) -> str:
    if job.price_fixed:
        return f"{job.price_fixed:,}円（固定）"
    if job.price_min and job.price_max:
        return f"{job.price_min:,}〜{job.price_max:,}円"
    if job.price_min:
        return f"{job.price_min:,}円〜"
    return "不明"


async def draft_application(job: Job) -> dict:
    user_prompt = USER_PROMPT_TEMPLATE.format(
        title=job.title,
        description=(job.description or "")[:1500],
        platform=job.platform,
        category=job.category.value if job.category else "other",
        analysis_notes=job.analysis_notes or "—",
        price=_format_price(job),
    )

    response = get_client().chat.completions.create(
        model="deepseek-chat",
        max_tokens=1024,
        messages=[
            {"role": "system", "content": inject_directives(SYSTEM_PROMPT, "execution")},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )

    text = (response.choices[0].message.content or "").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        result = json.loads(m.group()) if m else {}

    proposal = (result.get("proposal_text") or "").strip()
    if not proposal:
        raise RuntimeError("LLM が空の提案文を返しました")

    amount = result.get("proposed_amount")
    days = result.get("proposed_days")
    return {
        "proposal_text": proposal,
        "proposed_amount": int(amount) if isinstance(amount, (int, float)) else None,
        "proposed_days": int(days) if isinstance(days, (int, float)) else None,
    }
