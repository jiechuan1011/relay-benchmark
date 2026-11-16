"""静态站生成器 v2：拉取上游价格 JSON → 聚合 → 生成完整网页端

页面功能：站点排行榜（搜索/排序）、模型比价、数据来源标注。
输出 dist/，部署到 GitHub Pages（api.jiechuan1011.com）。
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

UNIT_IN = "per_1m_input_tokens"
UNIT_OUT = "per_1m_output_tokens"


def fetch_upstream() -> dict:
    """拉取上游 JSON：优先用本地 net_fetch.py（走代理），否则用 urllib 直连"""
    proxy_arg = [] if os.environ.get("SKIP_PROXY") else ["--proxy", PROXY]
    if FETCHER.exists():
        raw = subprocess.run(
            [sys.executable, str(FETCHER), UPSTREAM, *proxy_arg],
            capture_output=True, text=True, check=True,
        ).stdout
        # net_fetch.py 可能打印额外日志，找第一个 '{' 开始解析
        return json.loads(raw[raw.index("{"):])
    import urllib.request
    req = urllib.request.Request(UPSTREAM, headers={"User-Agent": "relay-benchmark"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def aggregate(records: list[dict]):
    """返回 (站点摘要列表, 热门模型比价列表)"""
    groups = defaultdict(list)
    for r in records:
        groups[r["provider_id"]].append(r)

    summaries = []
    for pid, rs in groups.items():
        inp = [r["price_usd"] for r in rs if r["unit"] == UNIT_IN]
        out = [r["price_usd"] for r in rs if r["unit"] == UNIT_OUT]
        models = {r["raw_model_name"] for r in rs}
        f = rs[0]
        summaries.append({
            "provider_id": pid, "provider_name": f["provider_name"],
            "channel_type": f.get("channel_type"),
            "model_count": len(models), "record_count": len(rs),
            "min_input": min(inp) if inp else None,
            "min_output": min(out) if out else None,
            "avg_input": round(sum(inp)/len(inp), 4) if inp else None,
            "avg_output": round(sum(out)/len(out), 4) if out else None,
            "captured_at": (f.get("captured_at") or "")[:19],
            "source_url": f.get("source_url"),
        })
    summaries.sort(key=lambda s: s["model_count"], reverse=True)

    # 热门模型比价：按模型名聚合，找最低价站点
    by_model = defaultdict(lambda: defaultdict(dict))
    for r in records:
        if r["unit"] == UNIT_IN:
            by_model[r["raw_model_name"]][r["provider_id"]] = {
                "provider_name": r["provider_name"], "price": r["price_usd"],
            }
    hot = ["claude-sonnet-4", "claude-opus", "gpt-5", "deepseek-v3", "gemini-2.5-pro", "kimi-k"]
    model_rows = []
    for model, providers in sorted(by_model.items()):
        if not any(h in model.lower() for h in hot):
            continue
        offers = sorted(({"provider": v["provider_name"], "price": v["price"]}
                         for v in providers.values()), key=lambda x: x["price"])
        if len(offers) >= 2:
            model_rows.append({"model": model, "offers": offers[:8]})
    model_rows.sort(key=lambda m: len(m["offers"]), reverse=True)
    return summaries, model_rows[:40]


def esc(v) -> str:
    return html.escape(str(v))


def render(env: dict, providers: list, models: list, generated_at: str) -> str:
    prov_json = json.dumps(providers, ensure_ascii=False).replace("</", "<\\/")
    model_json = json.dumps(models, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API 中转站实时测评 · jiechuan1011.com</title>
<style>
:root {{ --bg:#0d1117; --card:#161b22; --border:#30363d; --fg:#e6edf3; --dim:#8b949e; --acc:#58a6ff; }}
* {{ box-sizing: border-box; }}
body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; margin:0; background:var(--bg); color:var(--fg); }}
.wrap {{ max-width:1100px; margin:0 auto; padding:2rem 1rem; }}
h1 {{ margin:0 0 .3rem; font-size:1.6rem; }}
.meta {{ color:var(--dim); font-size:.85rem; margin-bottom:1.5rem; }}
.meta a {{ color:var(--acc); }}
.tabs {{ display:flex; gap:.5rem; margin-bottom:1rem; }}
.tabs button {{ background:var(--card); color:var(--dim); border:1px solid var(--border);
  padding:.5rem 1.1rem; border-radius:8px; cursor:pointer; font-size:.9rem; }}
.tabs button.on {{ color:var(--fg); border-color:var(--acc); }}
input#q {{ background:var(--card); color:var(--fg); border:1px solid var(--border);
  padding:.55rem .9rem; border-radius:8px; width:280px; font-size:.9rem; outline:none; }}
table {{ border-collapse:collapse; width:100%; font-size:.87rem; margin-top:1rem; }}
th,td {{ border-bottom:1px solid var(--border); padding:.55rem .7rem; text-align:left; }}
th {{ color:var(--dim); font-weight:600; cursor:pointer; user-select:none; white-space:nowrap; }}
th.num,td.num {{ text-align:right; }}
tr:hover td {{ background:#1c2129; }}
td a {{ color:var(--acc); text-decoration:none; }}
.badge {{ display:inline-block; background:#1f6feb33; color:var(--acc); border-radius:10px;
  padding:.05rem .5rem; font-size:.75rem; }}
.model-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px;
  padding:.9rem 1.1rem; margin-bottom:.8rem; }}
.model-card h3 {{ margin:0 0 .5rem; font-size:.95rem; word-break:break-all; }}
.offers {{ display:flex; flex-wrap:wrap; gap:.4rem; }}
.offers span {{ background:#21262d; border:1px solid var(--border); border-radius:6px;
  padding:.15rem .55rem; font-size:.8rem; }}
.offers span.best {{ border-color:#3fb950; color:#3fb950; }}
.src {{ color:var(--dim); font-size:.8rem; margin-top:2rem; line-height:1.6; }}
</style>
</head>
<body>
<div class="wrap">
<h1>🛰️ API 中转站实时测评</h1>
<p class="meta">
 数据快照 {esc(env["snapshot_date"])} · {len(providers)} 个站点 · {env["record_count"]} 条价格记录 ·
 来源 <a href="https://github.com/howardpen9/awesome-ai-api-proxy" target="_blank" rel="noopener">awesome-ai-api-proxy</a> ·
 生成于 {esc(generated_at)}
</p>
<div class="tabs">
 <button id="tab-prov" class="on" onclick="show('prov')">站点排行</button>
 <button id="tab-model" onclick="show('model')">模型比价</button>
</div>
<input id="q" placeholder="搜索站点 / 模型…" oninput="render()">

<div id="view-prov"><table id="tbl"><thead><tr>
 <th data-k="rank">#</th><th data-k="provider_name">站点</th><th data-k="channel_type">类型</th>
 <th data-k="model_count" class="num">模型数</th>
 <th data-k="min_input" class="num">最低输入价</th><th data-k="min_output" class="num">最低输出价</th>
 <th data-k="avg_input" class="num">平均输入价</th><th data-k="avg_output" class="num">平均输出价</th>
 <th data-k="captured_at">抓取时间</th>
</tr></thead><tbody></tbody></table></div>

<div id="view-model" style="display:none"></div>

<p class="src">
 ⚠ 本站聚合公开价格数据，仅供选站参考，不构成对任何站点的背书；价格以各站点官网为准。<br>
 数据每 6 小时自动更新 · 数据源记录均保留原始出处（source_url / captured_at）·
 <a href="https://github.com/jiechuan1011/relay-benchmark" target="_blank" rel="noopener">GitHub 仓库</a>
</p>
</div>
<script>
const PROV = {prov_json};
const MODELS = {model_json};
let tab = 'prov', sortK = 'rank', sortAsc = true;

function show(t) {{
  tab = t;
  document.getElementById('view-prov').style.display = t==='prov'?'':'none';
  document.getElementById('view-model').style.display = t==='model'?'':'none';
  document.getElementById('tab-prov').classList.toggle('on', t==='prov');
  document.getElementById('tab-model').classList.toggle('on', t==='model');
  render();
}}

function fmt(v) {{ return v == null ? '-' : '$' + v.toFixed(3); }}

function render() {{
  const q = document.getElementById('q').value.toLowerCase();
  if (tab === 'prov') {{
    let rows = PROV.map((p,i) => ({{...p, rank:i+1}}));
    if (q) rows = rows.filter(p => p.provider_name.toLowerCase().includes(q) || (p.channel_type||'').includes(q));
    rows.sort((a,b) => {{
      const va=a[sortK], vb=b[sortK];
      if (va==null) return 1; if (vb==null) return -1;
      return (typeof va==='number'? va-vb : String(va).localeCompare(String(vb))) * (sortAsc?1:-1);
    }});
    document.querySelector('#tbl tbody').innerHTML = rows.map(p => `<tr>
      <td>${{p.rank}}</td>
      <td>${{p.source_url?`<a href="${{p.source_url}}" target="_blank" rel="noopener">${{esc(p.provider_name)}}</a>`:esc(p.provider_name)}}</td>
      <td>${{esc(p.channel_type||'-')}}</td>
      <td class="num">${{p.model_count}}</td>
      <td class="num">${{fmt(p.min_input)}}</td><td class="num">${{fmt(p.min_output)}}</td>
      <td class="num">${{fmt(p.avg_input)}}</td><td class="num">${{fmt(p.avg_output)}}</td>
      <td>${{esc(p.captured_at)}}</td></tr>`).join('');
  }} else {{
    let ms = MODELS.filter(m => !q || m.model.toLowerCase().includes(q));
    document.getElementById('view-model').innerHTML = ms.map(m => `<div class="model-card">
      <h3>${{esc(m.model)}}</h3>
      <div class="offers">${{m.offers.map((o,i)=>`<span class="${{i===0?'best':''}}">${{esc(o.provider)}} ${{fmt(o.price)}}</span>`).join('')}}</div>
    </div>`).join('') || '<p class="meta">无匹配模型</p>';
  }}
}}

function esc(s) {{ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }}
document.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => {{
  const k = th.dataset.k;
  if (sortK===k) sortAsc=!sortAsc; else {{ sortK=k; sortAsc=true; }}
  render();
}});
render();
</script>
</body>
</html>"""


def main():
    env = fetch_upstream()
    providers, models = aggregate(env["records"])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(render(env, providers, models, generated_at), encoding="utf-8")
    (DIST / "data").mkdir(exist_ok=True)
    (DIST / "data" / "providers.json").write_text(
        json.dumps({"snapshot_date": env["snapshot_date"], "generated_at": generated_at,
                    "providers": providers}, ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "data" / "models.json").write_text(
        json.dumps({"snapshot_date": env["snapshot_date"], "models": models},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "data" / "prices.latest.json").write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    (DIST / "CNAME").write_text("api.jiechuan1011.com\n", encoding="utf-8")
    print(f"OK: {len(providers)} providers, {len(models)} hot models, {env['record_count']} records -> dist/")


if __name__ == "__main__":
    main()
