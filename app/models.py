"""数据模型：中转站 + 价格记录（含来源标注）"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PriceRecord(BaseModel):
    """一条标准化价格记录，来自上游数据源"""
    provider_id: str
    provider_name: str
    raw_model_name: str
    canonical_model: Optional[str] = None
    channel_type: Optional[str] = None
    unit: str
    price_usd: float
    source_url: Optional[str] = None
    captured_at: Optional[str] = None
    confidence: Optional[str] = None
    method: Optional[str] = None
    notes: Optional[str] = None


class SourceEnvelope(BaseModel):
    """上游数据源的信封信息"""
    schema_version: int
    snapshot_date: str
    generated_at: str
    record_count: int
    records: list[PriceRecord]


class ProviderSummary(BaseModel):
    """一个中转站的聚合摘要"""
    provider_id: str
    provider_name: str
    channel_type: Optional[str] = None
    model_count: int = 0
    record_count: int = 0
    min_input_price: Optional[float] = None
    min_output_price: Optional[float] = None
    avg_input_price: Optional[float] = None
    avg_output_price: Optional[float] = None
    captured_at: Optional[str] = None
    source_url: Optional[str] = None
    source: str = "awesome-ai-api-proxy"  # 来源标注
