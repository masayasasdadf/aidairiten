"""UI から設定可能なクレデンシャル (DB) → env (config.settings) の順に解決。

呼び出し側は get_credential('deepseek_api_key') のように key 名で引く。
キャッシュはしない（UI で更新したら次の参照で即反映するため）。
"""

from typing import Optional

from db.database import SessionLocal
from db.models import AppSetting

# UI で扱うクレデンシャル一覧
CREDENTIAL_KEYS = [
    "deepseek_api_key",
    "deepseek_base_url",
    "crowdworks_email",
    "crowdworks_password",
    "lancers_email",
    "lancers_password",
    "coconala_email",
    "coconala_password",
]


def get_credential(key: str, default: str = "") -> str:
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row and row.value:
            return row.value
    finally:
        db.close()
    # フォールバック: env 由来の pydantic settings
    try:
        from config import settings
        v = getattr(settings, key, None)
        if v:
            return str(v)
    except Exception:
        pass
    return default


def set_credential(key: str, value: str) -> None:
    db = SessionLocal()
    try:
        row = db.query(AppSetting).filter(AppSetting.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppSetting(key=key, value=value))
        db.commit()
    finally:
        db.close()


def all_credentials_masked() -> dict[str, dict]:
    """UI 表示用: DB に保存された値のみ参照（env 由来は含めない）。"""

    db = SessionLocal()
    try:
        rows = {r.key: (r.value or "") for r in db.query(AppSetting).all()}
    finally:
        db.close()

    out: dict[str, dict] = {}
    for k in CREDENTIAL_KEYS:
        v = rows.get(k, "")
        out[k] = {
            "set": bool(v),
            "preview": (("…" + v[-4:]) if len(v) > 4 else ("●" * len(v))) if v else "",
            "length": len(v),
        }
    return out
