"""神の声をエージェントの system prompt に差し込むためのヘルパ。"""

from db.database import SessionLocal
from db.models import Directive

_TARGET_LABEL = {
    "all": "全社向け",
    "analysis": "分析部宛",
    "execution": "制作部宛",
    "qc": "QC部宛",
}


def fetch_active(agent: str) -> list[Directive]:
    """agent ('analysis' / 'execution' / 'qc') 向けにアクティブな指示を取得。

    'all' 向けの全社指示と、その agent 個別の指示の両方を返す。
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(Directive)
            .filter(Directive.active.is_(True), Directive.target.in_(["all", agent]))
            .order_by(Directive.created_at.asc())
            .all()
        )
        # session 切ったあとも使えるように属性を引き出しておく
        return [
            Directive(
                id=r.id,
                target=r.target,
                instruction=r.instruction,
                active=r.active,
                created_at=r.created_at,
            )
            for r in rows
        ]
    finally:
        db.close()


def format_block(directives: list[Directive]) -> str:
    """SYSTEM_PROMPT 末尾に追記する文字列を生成。空ならから文字列。"""
    if not directives:
        return ""
    lines = [
        "",
        "## ⚡ 上層部からの最重要指示（他の指針より優先して従うこと）",
    ]
    for d in directives:
        scope = _TARGET_LABEL.get(d.target, d.target)
        lines.append(f"- [{scope}] {d.instruction}")
    return "\n".join(lines)


def inject(system_prompt: str, agent: str) -> str:
    """エージェント側の利便関数: system_prompt に神の声を追加して返す。"""
    return system_prompt + format_block(fetch_active(agent))
