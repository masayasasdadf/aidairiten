import json

from openai import OpenAI

from config import settings
from db.models import JobCategory, ExecutionType
from scrapers.base import RawJob

client = OpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)

SYSTEM_PROMPT = """あなたはAI総合商社の案件分析担当AIです。
クラウドソーシングプラットフォームから取得した案件を分析し、受注すべきかどうか判断します。

## 自社AI処理できる案件（inhouse）
- 記事・ブログ執筆（5,000字以内）
- LP・ランディングページ制作（シンプルなHTML/CSS）
- 翻訳（日英・英日・その他）
- SNS投稿文作成
- SEOライティング
- データ整形・フォーマット変換
- 商品説明文・キャッチコピー

## 外注すべき案件（outsource）
- 複雑なWebアプリ・システム開発
- 高度なデザイン（オリジナルイラスト、複雑なUI設計）
- 動画編集・映像制作
- 専門資格が必要な作業
- 5,000字超の大量執筆案件

## スキップすべき案件（skip）
- 最低単価を下回る案件
- 対面・電話必須
- 個人情報取扱いリスクが高い
- 納期が極端に短い（24時間以内）
- 内容が不明瞭・詐欺疑いのある案件

## 単価ライン
- 記事: 3,000円以上
- LP制作: 15,000円以上
- 翻訳: 5,000円以上
- その他: 3,000円以上"""

ANALYSIS_PROMPT_TEMPLATE = """以下の案件を分析してください。

タイトル: {title}
説明: {description}
単価: {price}
プラットフォーム: {platform}

以下のJSON形式で回答してください（他の文字は一切含めないこと）:
{{
  "category": "article|lp|translation|data_entry|sns|seo|other",
  "execution_type": "inhouse|outsource|skip",
  "score": 0-100,
  "analysis_notes": "判断理由を日本語で簡潔に",
  "skills_required": ["必要スキル1", "必要スキル2"]
}}"""


def _format_price(job: RawJob) -> str:
    if job.price_fixed:
        return f"{job.price_fixed:,}円（固定）"
    if job.price_min and job.price_max:
        return f"{job.price_min:,}〜{job.price_max:,}円"
    if job.price_min:
        return f"{job.price_min:,}円〜"
    return "不明"


async def analyze_job(job: RawJob) -> dict:
    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        title=job.title,
        description=job.description[:1000],
        price=_format_price(job),
        platform=job.platform,
    )

    response = client.chat.completions.create(
        model="deepseek-chat",
        max_tokens=512,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )

    text = (response.choices[0].message.content or "").strip()
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        result = json.loads(m.group()) if m else {}

    return {
        "category": result.get("category", "other"),
        "execution_type": result.get("execution_type", "skip"),
        "score": float(result.get("score", 0)),
        "analysis_notes": result.get("analysis_notes", ""),
        "skills_required": result.get("skills_required", []),
    }
