"""L1 聚合器：从上游 JSON 数据源拉取并聚合"""
from collections import defaultdict
from typing import Optional

import httpx

from .models import ProviderSummary, SourceEnvelope

UPSTREAM_URL = "https://raw.githubusercontent.com/howardpen9/awesome-ai-api-proxy/main/data/prices.latest.json"
PROXY = "http://127.0.0.1:7890"

# 模块级缓存，避免每次请求都拉上游
_cache: Optional[SourceEnvelope] = None


async def fetch_upstream() -> SourceEnvelope:
    """从上游拉取最新价格数据"""
    global _cache
    async with httpx.AsyncClient(proxy=PROXY, timeout=60) as client:
        resp = await client.get(UPSTREAM_URL)
        resp.raise_for_status()
        data = resp.json()
    env = SourceEnvelope(**data)
    _cache = env
    return env


async def get_cached() -> SourceEnvelope:
    """获取缓存数据，没有则现场拉"""
    return _cache if _cache else await fetch_upstream()


def aggregate_providers(env: SourceEnvelope) -> list[ProviderSummary]:
    """按站点聚合价格记录"""
    groups: dict[str, list] = defaultdict(list)
    for rec in env.records:
        groups[rec.provider_id].append(rec)

    summaries = []
    for pid, recs in groups.items():
        inputs = [r.price_usd for r in recs if r.unit == "per_1m_input_tokens"]
        outputs = [r.price_usd for r in recs if r.unit == "per_1m_output_tokens"]
        models = {r.raw_model_name for r in recs}
        first = recs[0]
        summaries.append(ProviderSummary(
            provider_id=pid,
            provider_name=first.provider_name,
            channel_type=first.channel_type,
            model_count=len(models),
            record_count=len(recs),
            min_input_price=min(inputs) if inputs else None,
            min_output_price=min(outputs) if outputs else None,
            avg_input_price=sum(inputs) / len(inputs) if inputs else None,
            avg_output_price=sum(outputs) / len(outputs) if outputs else None,
            captured_at=first.captured_at,
            source_url=first.source_url,
        ))
    summaries.sort(key=lambda s: s.record_count, reverse=True)
    return summaries
