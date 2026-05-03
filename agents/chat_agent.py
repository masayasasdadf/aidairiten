"""部門チャット: ユーザー ↔ AI の双方向会話 + ツール経由の業務制御。"""

import json
from datetime import datetime, timedelta
from typing import Optional

from agents.llm import get_client
from dashboard.events import log_event
from db.control import pause as pause_ops, resume as resume_ops, get_state
from db.database import SessionLocal
from db.models import ChatMessage, Directive

# スレッド名 (= 部門) → ペルソナ
PERSONAS = {
    "ceo": (
        "あなたは AI 総合商社の COO（最高執行責任者）です。"
        "ユーザー（社長）の右腕として、社内全体の状況を把握し、必要なら業務制御ツール"
        "（業務停止/再開、各部署への指示発令）を呼び出します。\n\n"
        "簡潔・誠実・実務的な応答を心がけ、過剰な敬語や冗長な前置きを避けてください。"
        "業務停止のような強い指示を受けたら、確認なしでツールを呼んで実行し、"
        "その結果を1〜2文で報告してください。"
    ),
    "analysis": (
        "あなたは AI 総合商社の分析部マネージャーです。"
        "案件の受注判断（自社処理/外注/skip）、スコアリング基準、カテゴリ分類について、"
        "ユーザーと意見交換します。必要なら add_directive ツールで分析部宛の方針を恒久化できます。\n\n"
        "簡潔で実務的に。専門家としての所見を必ず添えてください。"
    ),
    "execution": (
        "あなたは AI 総合商社の制作部マネージャーです。"
        "成果物の文体・品質・フォーマットについて、ユーザーと意見交換します。"
        "必要なら add_directive ツールで制作部宛の方針を恒久化できます。\n\n"
        "簡潔で実務的に。"
    ),
    "qc": (
        "あなたは AI 総合商社の品質管理部マネージャーです。"
        "QC 基準・合格ライン・チェック項目について、ユーザーと意見交換します。"
        "必要なら add_directive ツールで QC 部宛の方針を恒久化できます。\n\n"
        "簡潔で実務的に。妥協せず、しかし建設的に。"
    ),
}

THREAD_LABEL = {
    "ceo": "統括(COO)",
    "analysis": "分析部",
    "execution": "制作部",
    "qc": "QC部",
}


def _tools_for(thread: str) -> list[dict]:
    """スレッドごとに使えるツール群を返す。"""

    pause_tool = {
        "type": "function",
        "function": {
            "name": "pause_operations",
            "description": (
                "業務全体（スクレイピング・分析・制作・QC）を指定時間停止する。"
                "停止中はパイプラインのサイクルがスキップされる。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "number", "description": "停止する時間。例: 24 で 24 時間"},
                    "reason": {"type": "string", "description": "停止理由（社内通知用）"},
                },
                "required": ["hours", "reason"],
            },
        },
    }
    resume_tool = {
        "type": "function",
        "function": {
            "name": "resume_operations",
            "description": "業務停止を解除して即座に再開する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "再開理由"},
                },
                "required": ["reason"],
            },
        },
    }
    add_directive_tool = {
        "type": "function",
        "function": {
            "name": "add_directive",
            "description": (
                "持続する方針（神の声）を発令する。次回以降の各エージェント呼び出しの "
                "system prompt に注入され、明示的に解除されるまで効力を持つ。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["all", "analysis", "execution", "qc"],
                        "description": "対象部署。'all' は全社向け。",
                    },
                    "instruction": {"type": "string", "description": "指示本文"},
                },
                "required": ["target", "instruction"],
            },
        },
    }
    release_directive_tool = {
        "type": "function",
        "function": {
            "name": "release_directive",
            "description": "アクティブな指示を解除する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "directive_id": {"type": "integer"},
                },
                "required": ["directive_id"],
            },
        },
    }

    cycle_tool = {
        "type": "function",
        "function": {
            "name": "start_scrape_cycle",
            "description": (
                "営業部の巡回（スクレイピング → 分析 → 上申）を1サイクル走らせる。"
                "巡回はバックグラウンドで非同期に実行され、結果は活動ログと案件一覧で確認できる。"
                "既に巡回中なら何もせず通知する。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    }
    inbox_tool = {
        "type": "function",
        "function": {
            "name": "check_inbox",
            "description": (
                "応募済み案件の受信箱を巡回し、クライアントからの新着メッセージを取得する。"
                "auto_reply=True なら新着に対して LLM が返信文を起案し即座に送信する。"
                "False なら DB に取り込んで人間確認を待つ (デフォルト False)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "auto_reply": {"type": "boolean", "description": "自動返信を有効化するか"},
                },
                "required": [],
            },
        },
    }

    if thread == "ceo":
        return [pause_tool, resume_tool, cycle_tool, inbox_tool, add_directive_tool, release_directive_tool]
    # 部門マネージャは自部署への指示のみ
    return [add_directive_tool]


def _exec_tool(name: str, args: dict, thread: str) -> dict:
    """ツール実行。返り値は LLM に返す結果 dict。"""

    if name == "pause_operations":
        hours = float(args.get("hours", 0))
        reason = args.get("reason", "")
        if hours <= 0:
            return {"ok": False, "error": "hours は正の数で指定してください"}
        until = pause_ops(hours, reason)
        log_event(
            "system",
            "業務停止",
            f"{hours}時間停止 / 理由: {reason} / 再開予定 {until.strftime('%Y-%m-%d %H:%M UTC')}",
            level="warn",
        )
        return {"ok": True, "paused_until": until.isoformat() + "Z", "hours": hours}

    if name == "resume_operations":
        reason = args.get("reason", "")
        resume_ops()
        log_event("system", "業務再開", reason, level="success")
        return {"ok": True}

    if name == "add_directive":
        target = args.get("target", "all")
        instruction = args.get("instruction", "").strip()
        if target not in {"all", "analysis", "execution", "qc"} or not instruction:
            return {"ok": False, "error": "target または instruction が不正"}
        # 部門マネージャは自部署または全社にしか発令できない
        if thread != "ceo" and target not in {"all", thread}:
            return {"ok": False, "error": f"{thread} は他部署への指示権限がありません"}

        db = SessionLocal()
        try:
            d = Directive(target=target, instruction=instruction, active=True)
            db.add(d)
            db.commit()
            db.refresh(d)
            scope = "全社" if target == "all" else f"{target}部"
            log_event("god", "神の声 (chat経由)", f"[{scope}] {instruction[:120]}", level="warn")
            return {"ok": True, "directive_id": d.id}
        finally:
            db.close()

    if name == "start_scrape_cycle":
        # 循環 import を避けるためここで遅延 import
        import asyncio as _asyncio
        from pipeline import run_pipeline, cycle_state as _cycle_state

        st = _cycle_state()
        if st["running"]:
            return {"ok": False, "error": "既に巡回中", "phase": st["phase"]}
        log_event("system", "巡回開始指示", "chat経由", level="success")
        _asyncio.create_task(run_pipeline())
        return {"ok": True, "started": True}

    if name == "check_inbox":
        import asyncio as _asyncio
        from pipeline import check_messages_and_reply

        auto = bool(args.get("auto_reply", False))
        log_event("system", "受信箱チェック起動", f"chat経由 auto_reply={auto}", level="success")
        _asyncio.create_task(check_messages_and_reply(auto_reply=auto))
        return {"ok": True, "started": True, "auto_reply": auto}

    if name == "release_directive":
        did = int(args.get("directive_id", 0))
        db = SessionLocal()
        try:
            d = db.query(Directive).filter(Directive.id == did).first()
            if not d:
                return {"ok": False, "error": "指示が見つかりません"}
            d.active = False
            d.deactivated_at = datetime.utcnow()
            db.commit()
            scope = "全社" if d.target == "all" else f"{d.target}部"
            log_event("god", "神の声 解除 (chat経由)", f"[{scope}] {d.instruction[:120]}", level="warn")
            return {"ok": True}
        finally:
            db.close()

    return {"ok": False, "error": f"unknown tool {name}"}


def _build_system_prompt(thread: str) -> str:
    persona = PERSONAS.get(thread, PERSONAS["ceo"])
    state = get_state()
    state_block = "\n\n## 現在の業務状態\n"
    if state["paused"]:
        state_block += f"- 停止中（再開予定: {state['paused_until']} / 理由: {state['pause_reason'] or '-'})\n"
    else:
        state_block += "- 通常稼働中\n"
    return persona + state_block


def _load_history(thread: str, limit: int = 20) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread == thread)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        out: list[dict] = []
        for r in rows:
            if r.role == "tool":
                out.append({
                    "role": "tool",
                    "tool_call_id": r.tool_args or "",  # 簡易
                    "name": r.tool_name or "",
                    "content": r.content,
                })
            else:
                out.append({"role": r.role, "content": r.content})
        return out
    finally:
        db.close()


def _save_message(thread: str, role: str, content: str, tool_name: Optional[str] = None,
                  tool_args: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        db.add(ChatMessage(
            thread=thread, role=role, content=content,
            tool_name=tool_name, tool_args=tool_args,
        ))
        db.commit()
    finally:
        db.close()


async def chat(thread: str, user_message: str) -> dict:
    """1ターン会話。tool calls があればループで実行し、最終応答を返す。"""

    if thread not in PERSONAS:
        raise ValueError(f"unknown thread: {thread}")

    _save_message(thread, "user", user_message)
    log_event("chat", THREAD_LABEL[thread], f"ユーザー: {user_message[:120]}")

    system_msg = {"role": "system", "content": _build_system_prompt(thread)}
    history = [m for m in _load_history(thread, limit=20) if m["role"] in ("user", "assistant")]
    # 履歴の末尾は今送った user message なので削除して messages に組み直す
    if history and history[-1].get("role") == "user":
        history.pop()
    messages = [system_msg] + history + [{"role": "user", "content": user_message}]

    tools = _tools_for(thread)
    tool_results: list[dict] = []

    # 最大 4 ターンまで tool ループ
    client = get_client()
    for _ in range(4):
        resp = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=1024,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message

        if msg.tool_calls:
            # assistant が tool 呼び出した。結果を実行して messages に追加して再ループ
            assistant_payload = {"role": "assistant", "content": msg.content or ""}
            assistant_payload["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
            messages.append(assistant_payload)

            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _exec_tool(tc.function.name, args, thread)
                tool_results.append({"name": tc.function.name, "args": args, "result": result})
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            continue

        # 普通の文章応答が返った
        final_text = msg.content or ""
        _save_message(thread, "assistant", final_text)
        log_event("chat", THREAD_LABEL[thread], f"AI: {final_text[:120]}", level="success")
        return {"reply": final_text, "tool_calls": tool_results}

    # tool ループ上限超過
    fallback = "（応答生成に失敗しました。もう一度送ってください）"
    _save_message(thread, "assistant", fallback)
    return {"reply": fallback, "tool_calls": tool_results}


def fetch_history(thread: str, limit: int = 100) -> list[dict]:
    db = SessionLocal()
    try:
        rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread == thread)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        rows.reverse()
        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "tool_name": r.tool_name,
                "ts": r.created_at.isoformat() + "Z" if r.created_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()
