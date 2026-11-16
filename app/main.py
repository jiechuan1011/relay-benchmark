"""FastAPI 应用：L1 排行榜"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .aggregator import aggregate_providers, get_cached

app = FastAPI(title="API 中转站实时测评", version="0.1.0")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    env = await get_cached()
    summaries = aggregate_providers(env)
    return templates.TemplateResponse(request, "index.html", {
        "snapshot_date": env.snapshot_date,
        "record_count": env.record_count,
        "provider_count": len(summaries),
        "providers": summaries,
    })


@app.get("/api/providers")
async def api_providers():
    env = await get_cached()
    return {"snapshot_date": env.snapshot_date, "providers": [s.model_dump() for s in aggregate_providers(env)]}


@app.get("/api/prices")
async def api_prices(provider_id: str | None = None):
    env = await get_cached()
    recs = env.records
    if provider_id:
        recs = [r for r in recs if r.provider_id == provider_id]
    return {"snapshot_date": env.snapshot_date, "count": len(recs), "records": [r.model_dump() for r in recs]}
