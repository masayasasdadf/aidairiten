from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class RawJob:
    platform: str
    external_id: str
    url: str
    title: str
    description: str
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    price_fixed: Optional[int] = None
    deadline: Optional[datetime] = None
    client_name: str = ""
    skills_required: list[str] = field(default_factory=list)


class BaseScraper(ABC):
    platform_name: str = ""

    @abstractmethod
    async def fetch_jobs(self) -> list[RawJob]:
        """新着案件を取得して返す"""
        ...

    def _parse_price(self, text: str) -> Optional[int]:
        """「10,000円」「¥10000」などを整数に変換"""
        if not text:
            return None
        import re
        digits = re.sub(r"[^\d]", "", text)
        return int(digits) if digits else None
