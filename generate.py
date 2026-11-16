"""静态站生成器：拉取上游价格 JSON → 聚合 → 生成静态页面 + 数据文件

纯标准库实现，输出到 dist/，可直接部署到 GitHub Pages。
上游：awesome-ai-api-proxy 的 data/prices.latest.json（每条带 source_url/captured_at）
"""
import html
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
FETCHER = Path(r"D:\dsh\scripts\net_fetch.py")
PROXY = "http://127.0.0.1:7890"
UPSTREAM = "https://raw.githubusercontent.com/howardpen9/awesome-ai-api-proxy/main/data/prices.latest.json"

UNIT_LABEL = {
    "per_1m_input_tokens": "输入 $/1M",
    "per_1m_output_tokens": "输出 $/1M",
    "per_1m_input_cache_read_tokens": "缓存读 $/1M",
}


def fetch_upstream() -> dict:
    """用工作区 net_fetch.py（走代理）拉上游 JSON"""
    proxy = None if os.environ.get("SKIP_PROXY") else ["--proxy", PROXY]
    raw = subprocess.run(
        [sys.executable, str(FETCHER), UPSTREAM, *(proxy or [])],
        capture_output=True, text=True, check=True,
    ).stdout
    # net_fetch.py 可能打印额外日志，找第一个 '{' 开始解析
    return json.loads(raw[raw.index("{"):])


def aggregate(records: list[dict]) -> list[dict]:
    groups = defaultdict(list)
    for r in records:
        groups[r["provider_id"]].append(r)
    summaries = []
    for pid, rs in groups.items():
        inp = [r["price_usd"] for r in rs if r["unit"] == "per_1m_input_tokens"]
        out = [r["price_usd"] for r in rs if r["unit"] == "per_1m_output_tokens"]
        models = {r["raw_model_name"] for r in rs}
        f = rs[0]
        summaries.append({
            "provider_id": pid,
            "provider_name": f["provider_name"],
            "channel_type": f.get("channel_type"),
            "model_count": len(models),
            "record_count": len(rs),
            "min_input": min(inp) if inp else None,
            "min_output": min(out) if out else None,
            "avg_input": round(sum(inp) / len(inp), 4) if inp else None,
            "avg_output": round(sum(out) / len(out), 4) if out else None,
            "captured_at": (f.get("captured_at") or "")[:19],
            "source_url": f.get("source_url"),
        })
    summaries.sort(key=lambda s: s["model_count"], reverse=True)
    return summaries


def esc(v) -> str:
    return html.escape(str(v))


def render(env: dict, summaries: list[dict], generated_at: str) -> str:
    rows = []
    for i, p in enumerate(summaries, 1):
        name = esc(p["provider_name"])
        if p["source_url"]:
            name = f'<a href="{esc(p["source_url"])}" target="_blank" rel="noopener">{name}</a>'
        def num(v): return f'{v:.3f}' if v is not None else '-'
        rows.append(
            f"<tr><td>{i}</td><td>{name}</td><td>{esc(p['channel_type'] or '-')}</td>"
            f"<td class='num'>{p['model_count']}</td>"
            f"<td class='num'>{num(p['min_input'])}</td><td class='num'>{num(p['min_output'])}</td>"
            f"<td class='num'>{num(p['avg_input'])}</td><td class='num'>{num(p['avg_output'])}</td>"
            f"<td>{esc(p['captured_at'])}</td></tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API 中转站实时测评 · jiechuan1011.com</title>
<style>
 body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; margin: 2rem auto; max-width: 1100px; color: #222; }}
 h1 {{ margin-bottom: .2rem; }}
 .meta {{ color: #666; font-size: .9rem; margin-bottom: 1.2rem; }}
 input {{ padding: 6px 10px; width: 260px; margin-bottom: 1rem; }}
 table {{ border-collapse: collapse; width: 100%; font-size: .88rem; }}
 th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
 th {{ background: #f5f5f5; cursor: pointer; }}
 tr:hover {{ background: #fafafa; }}
 .num {{ text-align: right; }}
 .src {{ color: #888; font-size: .85rem; margin-top: 1.5rem; }}
</style>
</head>
<body>
<h1>API 中转站实时测评</h1>
<p class="meta">
 数据快照：{esc(env["snapshot_date"])} · 共 {len(summaries)} 个站点 · {env["record_count"]} 条价格记录 ·
 数据来源：<a href="https://github.com/howardpen9/awesome-ai-api-proxy" target="_blank" rel="noopener">awesome-ai-api-proxy</a> ·
 本页生成于 {esc(generated_at)}
</p>
<input id="q" placeholder="搜索站点名…" oninput="filter()">
<table id="tbl">
 <thead><tr>
  <th>#</th><th>站点</th><th>类型</th><th>模型数</th>
  <th>最低输入价</th><th>最低输出价</th><th>平均输入价</th><th>平均输出价</th><th>抓取时间</th>
 </tr></thead>
 <tbody>
 {"".join(rows)}
 </tbody>
</table>
<p class="src">⚠ 本榜单聚合公开价格数据，仅供选站参考，不构成对任何站点的背书。价格以各站点官网为准。</p>
<script>
function filter() {{
  const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('#tbl tbody tr').forEach(tr => {{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


def main():
    env = fetch_upstream()
    if env.get("record_count") != len(env.get("records", [])):
        print(f"⚠ record_count 不一致: {env.get('record_count')} vs {len(env.get('records', []))}，以实际为准")
    summaries = aggregate(env["records"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(render(env, summaries, generated_at), encoding="utf-8")
    (DIST / "data").mkdir(exist_ok=True)
    (DIST / "data" / "providers.json").write_text(
        json.dumps({"snapshot_date": env["snapshot_date"], "generated_at": generated_at, "providers": summaries},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "data" / "prices.latest.json").write_text(
        json.dumps(env, ensure_ascii=False), encoding="utf-8")
    (DIST / "CNAME").write_text("api.jiechuan1011.com\n", encoding="utf-8")
    print(f"OK: {len(summaries)} 站点, {env['record_count']} 条记录, 快照 {env['snapshot_date']} → dist/")


if __name__ == "__main__":
    main()
