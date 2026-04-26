from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, Enum as SAEnum
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
    INHOUSE = "inhouse"          # 自社AI処理予定
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


class Deliverable(Base):
    __tablename__ = "deliverables"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, nullable=False)
    content = Column(Text)
    qc_passed = Column(Boolean, nullable=True)
    qc_notes = Column(Text)
    iteration = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    job = relationship("Job", back_populates="deliverable", foreign_keys=[job_id],
                       primaryjoin="Deliverable.job_id == Job.id")
