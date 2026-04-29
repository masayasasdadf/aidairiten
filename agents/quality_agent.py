import json

from agents.directives import inject as inject_directives
from agents.llm import get_client
from db.models import Job

SYSTEM_PROMPT = """あなたはAI総合商社の品質管理担当AIです。
制作した成果物がクライアントの要件を満たしているか厳密に審査します。

## 審査基準
1. **要件充足**: クライアントの要求事項が満たされているか
2. **品質**: 文章の自然さ、正確性、読みやすさ
3. **完成度**: 未完成・途中終了がないか
4. **適切性**: 業種・ターゲットに合っているか
5. **法的問題**: 誇大広告・著作権侵害などがないか"""

QC_PROMPT = """以下の案件の成果物を品質審査してください。

## 案件情報
タイトル: {title}
要件: {description}

## 成果物
{content}

以下のJSON形式で回答してください（他の文字は一切含めないこと）:
{{
  "passed": true|false,
  "score": 0-100,
  "issues": ["問題点1", "問題点2"],
  "improvements": ["改善提案1", "改善提案2"],
  "summary": "審査結果の要約（日本語）"
}}"""


async def check_quality(job: Job, content: str) -> dict:
    prompt = QC_PROMPT.format(
        title=job.title,
        description=(job.description or "")[:800],
        content=content[:3000],
    )

    response = get_client().chat.completions.create(
        model="deepseek-chat",
        max_tokens=512,
        messages=[
            {"role": "system", "content": inject_directives(SYSTEM_PROMPT, "qc")},
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
        "passed": bool(result.get("passed", False)),
        "score": float(result.get("score", 0)),
        "issues": result.get("issues", []),
        "improvements": result.get("improvements", []),
        "summary": result.get("summary", ""),
    }
