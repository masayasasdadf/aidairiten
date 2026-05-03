from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
import enum

from db.database import Base


class JobCategory(str, enum.Enum):
    ARTICLE = "article"          # 記事・コンテンツ執筆
    LP = "lp"                    # LP・ウェブサイト制作
    TRANSLATION = "translation"  # 翻訳
    DATA_ENTRY = "data_entry"    # データ入力・整形
    SNS = "sns"                  # SNS投稿文
    SEO = "seo"                  # SEOライティング
    OTHER = "other"              # その他


class JobStatus(str, enum.Enum):
    NEW = "new"                  # 新着・未処理
    ANALYZING = "analyzing"      # 分析中
    REPORTED = "reported"        # 営業部上申中（ユーザーのGO待ち）
    APPLYING = "applying"        # 応募文起案・送信中
    APPLIED = "applied"          # 応募送信済み（クライアント返信待ち）
    REPLIED = "replied"          # クライアントから返信あり、やり取り中
    WON = "won"                  # 受注確定 → 制作開始可
    LOST = "lost"                # 返信なし / 不採用
    INHOUSE = "inhouse"          # (旧) 自社AI処理予定
    OUTSOURCE = "outsource"      # 外注予定（発注先待ち）
    SKIPPED = "skipped"          # スキップ
    IN_PROGRESS = "in_progress"  # 生産中
    QC = "qc"                    # 品質チェック中
    PENDING_APPROVAL = "pending_approval"  # 人間の最終承認待ち
    APPROVED = "approved"        # 承認済み・納品可能
    DELIVERED = "delivered"      # 納品済み
    REJECTED = "rejected"        # 品質チェックNG


class ExecutionType(str, enum.Enum):
    INHOUSE = "inhouse"
    OUTSOURCE = "outsource"


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    platform = Column(String(50), nullable=False)       # crowdworks / lancers / coconala etc.
    external_id = Column(String(200), unique=True)      # プラットフォーム上のID
    url = Column(String(500))
    title = Column(String(500), nullable=False)
    description = Column(Text)
    price_min = Column(Integer)
    price_max = Column(Integer)
    price_fixed = Column(Integer)
    category = Column(SAEnum(JobCategory), default=JobCategory.OTHER)
    status = Column(SAEnum(JobStatus), default=JobStatus.NEW)
    execution_type = Column(SAEnum(ExecutionType), nullable=True)
    deadline = Column(DateTime, nullable=True)
    client_name = Column(String(200))
    skills_required = Column(Text)                      # JSON list
    analysis_notes = Column(Text)                       # AI分析メモ
    score = Column(Float, default=0.0)                  # 案件スコア（0-100）
    discovered_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    deliverable = relationship("Deliverable", back_populates="job", uselist=False)


class Directive(Base):
    """神の声: ユーザーから AI エージェントへの上書き指示。

    target: 'all' / 'analysis' / 'execution' / 'qc'
    アクティブなものは各エージェントの system prompt 末尾に注入される。
    """

    __tablename__ = "directives"

    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(50), nullable=False, default="all")
    instruction = Column(Text, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    deactivated_at = Column(DateTime, nullable=True)


class ChatMessage(Base):
    """部門との会話履歴。thread ∈ {'ceo','analysis','execution','qc'}"""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread = Column(String(20), nullable=False, index=True)
    role = Column(String(20), nullable=False)        # 'user' / 'assistant' / 'tool'
    content = Column(Text, nullable=False, default="")
    tool_name = Column(String(50), nullable=True)    # tool 結果メッセージの場合
    tool_args = Column(Text, nullable=True)          # JSON 文字列
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemControl(Base):
    """シングルトン (id=1): 業務全体の制御フラグ。

    pipeline 起動時に paused_until をチェックし、
    今が past なら通常稼働、future なら今回のサイクルをスキップ。
    """

    __tablename__ = "system_control"

    id = Column(Integer, primary_key=True, default=1)
    paused_until = Column(DateTime, nullable=True)
    pause_reason = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSetting(Base):
    """API キー・各プラットフォーム認証情報など、UI から設定可能な値。

    env vars よりこちらが優先される。値は平文 (本番運用なら Vault/KMS 推奨)。
    """

    __tablename__ = "app_settings"

    key = Column(String(80), primary_key=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EventLog(Base):
    """活動ログの永続化 (Render コールドスタートでもメモリ deque を復元)。"""

    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String(50), nullable=False, index=True)
    action = Column(String(200), nullable=False)
    detail = Column(Text, nullable=False, default="")
    job_id = Column(Integer, nullable=True, index=True)
    level = Column(String(20), nullable=False, default="info")
    ts = Column(DateTime, default=datetime.utcnow, index=True)


class Application(Base):
    """応募記録: 1件の job に対して 1つ作成される (再応募は版数を上げる)。"""

    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    proposal_text = Column(Text, nullable=False)
    proposed_amount = Column(Integer, nullable=True)        # 提案金額(円)
    proposed_days = Column(Integer, nullable=True)          # 提案納期(日)
    submitted = Column(Boolean, default=False, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)                     # 送信失敗時の理由
    created_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    """クライアントとのやり取り 1通分。"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)             # 'client' / 'us'
    content = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    external_id = Column(String(200), nullable=True, unique=True)  # CW側のメッセージID重複防止
    handled = Column(Boolean, default=False, nullable=False)       # AI返信済みフラグ


class Deliverable(Base):
    __tablename__ = "deliverables"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    content = Column(Text)
    qc_passed = Column(Boolean, nullable=True)
    qc_notes = Column(Text)
    iteration = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("Job", back_populates="deliverable")
