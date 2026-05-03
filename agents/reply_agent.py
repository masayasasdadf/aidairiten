"""クライアントとのメッセージやり取りに対する返信案を起案する。"""

from agents.directives import inject as inject_directives
from agents.llm import get_client
from db.models import Job, Message

SYSTEM_PROMPT = """あなたはAI総合商社のクライアント対応マネージャーです。
クラウドソーシング案件の応募後、クライアントから来たメッセージに対して
適切な返信文を起案します。

## 返信の鉄則
- 200〜400字。長文は厳禁
- 質問には端的に回答 → 必要なら追加で1点だけ補足
- 期日・金額の確約は慎重に。曖昧なら「確認次第お伝えします」
- 不明点があれば 1 つだけ逆質問
- 過度な敬語は避けつつ、ビジネスマナーは守る
- AI 活用は隠さない"""


USER_PROMPT_TEMPLATE = """以下の応募中案件の最新メッセージに対する返信を起案してください。

## 案件情報
タイトル: {title}
案件説明: {description}

## 会話履歴 (古い順)
{history}

## 出力
返信文のみを出力してください。前置きや説明は不要。"""


def _format_history(messages: list[Message]) -> str:
    if not messages:
        return "(履歴なし)"
    lines = []
    for m in messages:
        who = "クライアント" if m.sender == "client" else "自社"
        ts = m.sent_at.strftime("%m/%d %H:%M") if m.sent_at else ""
        lines.append(f"[{ts}] {who}: {m.content}")
    return "\n".join(lines)


async def draft_reply(job: Job, history: list[Message]) -> str:
    response = get_client().chat.completions.create(
        model="deepseek-chat",
        max_tokens=600,
        messages=[
            {"role": "system", "content": inject_directives(SYSTEM_PROMPT, "execution")},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                title=job.title,
                description=(job.description or "")[:600],
                history=_format_history(history),
            )},
        ],
    )
    return (response.choices[0].message.content or "").strip()
