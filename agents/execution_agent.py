from agents.directives import inject as inject_directives
from agents.llm import get_client
from db.models import Job, JobCategory

SYSTEM_PROMPT = """あなたはAI総合商社の制作担当AIです。
クライアントから依頼された案件を高品質に仕上げます。

## 制作ルール
- 日本語は自然で読みやすい文体
- 指定文字数・フォーマットを厳守
- クライアントの業種・ターゲット層を考慮
- 誇張・虚偽のない誠実な表現
- SEOを意識した場合はキーワードを自然に組み込む"""

PROMPTS = {
    JobCategory.ARTICLE: """以下の案件要件に基づいて記事を執筆してください。

案件タイトル: {title}
案件内容: {description}

## 執筆要件
- 読者にとって価値ある内容を提供する
- 見出しを適切に使用する（H2, H3）
- 自然な文体で読みやすく
- 指定がない場合は2,000字程度

記事本文のみを出力してください。""",

    JobCategory.LP: """以下の案件要件に基づいてランディングページのHTMLを作成してください。

案件タイトル: {title}
案件内容: {description}

## 制作要件
- レスポンシブデザイン（モバイル対応）
- キャッチコピー・ベネフィット・CTA（行動喚起）を含む
- シンプルで読みやすいレイアウト
- インラインCSSを使用（外部ファイル不要）

完全なHTMLコードのみを出力してください。""",

    JobCategory.TRANSLATION: """以下の案件要件に基づいて翻訳を行ってください。

案件タイトル: {title}
案件内容（翻訳対象テキストを含む）: {description}

## 翻訳要件
- 原文の意味・ニュアンスを忠実に再現
- 自然な日本語（または指定言語）に
- 専門用語は適切に処理

翻訳文のみを出力してください。""",

    JobCategory.SNS: """以下の案件要件に基づいてSNS投稿文を作成してください。

案件タイトル: {title}
案件内容: {description}

## 制作要件
- 指定プラットフォームの文字数制限を考慮
- エンゲージメントを高める工夫
- ハッシュタグを適切に追加

投稿文のみを出力してください。""",

    JobCategory.SEO: """以下の案件要件に基づいてSEO記事を執筆してください。

案件タイトル: {title}
案件内容: {description}

## 執筆要件
- メインキーワードを適切な頻度で使用
- 検索意図に応えるコンテンツ
- 見出し構造を最適化（H1〜H3）
- 2,000〜3,000字程度

記事本文のみを出力してください。""",

    JobCategory.DATA_ENTRY: """以下の案件要件に基づいてデータ整形・変換を行ってください。

案件タイトル: {title}
案件内容: {description}

指定された形式で処理結果のみを出力してください。""",
}

DEFAULT_PROMPT = """以下の案件を遂行してください。

案件タイトル: {title}
案件内容: {description}

成果物のみを出力してください。"""


async def execute_job(job: Job) -> str:
    template = PROMPTS.get(job.category, DEFAULT_PROMPT)
    prompt = template.format(
        title=job.title,
        description=job.description or "",
    )

    response = get_client().chat.completions.create(
        model="deepseek-chat",
        max_tokens=4096,
        messages=[
            {"role": "system", "content": inject_directives(SYSTEM_PROMPT, "execution")},
            {"role": "user", "content": prompt},
        ],
    )

    return response.choices[0].message.content or ""
