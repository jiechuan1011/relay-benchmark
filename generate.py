"""静态站生成器 v3：价格数据 + 相对倍率（以 OpenRouter 为基准）

改进点：
1. 性价比核心指标改为「相对 OpenRouter 倍率」（中位数），替代误导性的最低/平均价
2. 站点链接改用上游 providers.yaml 的官网地址（修复 API 域名点不开的问题）
3. 模型名归一化 + canonical 别名映射，跨站可比
4. 模型比价页展示基准价与倍率

纯标准库实现，输出 dist/，部署 GitHub Pages（rank.jiechuan1011.com）。
"""
import html
import json
import os
import re
import statistics
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
FETCHER = Path(r"D:\dsh\scripts\net_fetch.py")
PROXY = "http://127.0.0.1:7890"
BASE = "https://raw.githubusercontent.com/howardpen9/awesome-ai-api-proxy/main/data/"
UPSTREAM_PRICES = BASE + "prices.latest.json"
UPSTREAM_PROVIDERS = BASE + "providers.yaml"
UPSTREAM_CANONICAL = BASE + "canonical-models.yaml"

UNIT_IN = "per_1m_input_tokens"
UNIT_OUT = "per_1m_output_tokens"
BASELINE = "openrouter"
MAX_RATIO = 50.0  # 超过此倍率视为疑似单位/异常报价，不计入中位数

# 官网地址覆盖：上游 providers.yaml 给的可能是 API 域名/价格页，换成更适合点开的入口
HOME_OVERRIDES = {
    "wappkit": "https://wappkit.com",
}

DATE_SUFFIX = re.compile(r"-(\d{8}|\d{4}-\d{2}-\d{2})$")
VENDOR_PREFIX = re.compile(r"^(openai|anthropic|google|deepseek|xai|moonshotai|moonshot|qwen|bytedance|minimaxai|minimax|meta-llama|meta|mistralai|cohere|amazon|nvidia|moondream|inception|bria)/")
NOISE_SUFFIX = re.compile(r"-(thinking|coding|preview|latest|ccmax|aws|vertex|azure|beta|exp)$")


def fetch(url: str) -> bytes:
    """拉取上游内容；非 SKIP_PROXY 时走本地代理"""
    handlers = []
    if not os.environ.get("SKIP_PROXY"):
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={"User-Agent": "relay-benchmark"})
    with opener.open(req, timeout=60) as resp:
        return resp.read()


def unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    return v


def parse_providers(text: str) -> list[dict]:
    """极简 YAML 子集解析：只取 name/url/type/status/model_count"""
    entries, cur = [], None
    for line in text.splitlines():
        m = re.match(r"\s*-\s+name:\s*(.+?)\s*$", line)
        if m:
            if cur:
                entries.append(cur)
            cur = {"name": unquote(m.group(1))}
            continue
        if cur is None:
            continue
        m2 = re.match(r"\s+(url|type|status|model_count|last_verified):\s*(.+?)\s*$", line)
        if m2:
            k, v = m2.group(1), unquote(m2.group(2))
            if k == "model_count":
                try:
                    v = int(v)
                except ValueError:
                    pass
            cur[k] = v
        elif re.match(r"^\S", line) and not line.startswith("#"):
            entries.append(cur)
            cur = None
    if cur:
        entries.append(cur)
    return entries


def parse_canonical(text: str) -> dict:
    """返回 {alias_lower: canonical}，同时返回 {canonical: tier}"""
    alias_map, tiers = {}, {}
    cur, in_aliases = None, False
    for line in text.splitlines():
        m = re.match(r"\s*-\s+canonical:\s*(\S+)\s*$", line)
        if m:
            cur, in_aliases = m.group(1), False
            continue
        if cur is None:
            continue
        if re.match(r"\s+aliases:\s*$", line):
            in_aliases = True
            continue
        mt = re.match(r"\s+tier:\s*(\d+)\s*$", line)
        if mt:
            tiers[cur] = int(mt.group(1))
            continue
        if in_aliases:
            ma = re.match(r"\s+-\s+(\S+)\s*$", line)
            if ma:
                alias_map[ma.group(1).lower()] = cur
                continue
            if re.match(r"\s+\w+:|\s*-\s+\w+:", line):
                in_aliases = False
    return alias_map, tiers


def norm_model(name: str) -> str:
    """模型名归一化：去厂商前缀、日期后缀、噪声后缀，统一分隔符"""
    s = name.strip().lower()
    s = VENDOR_PREFIX.sub("", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = s.replace(".", "-")
    s = DATE_SUFFIX.sub("", s)
    for _ in range(2):
        s = NOISE_SUFFIX.sub("", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", name.lower())


def pick_ratio(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def build(env: dict, providers_yaml: str, canonical_yaml: str):
    recs = env["records"]
    provider_meta = parse_providers(providers_yaml)
    alias_map, tiers = parse_canonical(canonical_yaml)

    # 站点元信息索引（名称归一化 → 条目）
    meta_by_name = {}
    for p in provider_meta:
        if p.get("url"):
            meta_by_name.setdefault(norm_name(p["name"]), p)

    def station_home(name: str) -> tuple[str | None, dict]:
        m = meta_by_name.get(norm_name(name))
        if m:
            return m["url"], m
        # 退化匹配：前缀包含
        n = norm_name(name)
        for k, v in meta_by_name.items():
            if k and (k in n or n in k):
                return v["url"], v
        return None, {}

    def canon_of(raw: str) -> str:
        low = raw.strip().lower()
        if low in alias_map:
            return alias_map[low]
        return norm_model(raw)

    # 基准价：OpenRouter（参考）+ 全网同模型最低价（性价比主指标）
    base_in, base_out = {}, {}
    for r in recs:
        if r["provider_id"] != BASELINE:
            continue
        c = canon_of(r["raw_model_name"])
        if r["unit"] == UNIT_IN:
            base_in[c] = r["price_usd"]
        elif r["unit"] == UNIT_OUT:
            base_out[c] = r["price_usd"]

    # 全网同模型最低价：只统计「至少 2 家站同时报价」的模型，否则比值恒为 1 无意义
    price_by_model: dict[str, list[float]] = defaultdict(list)
    for r in recs:
        if r["unit"] == UNIT_IN:
            price_by_model[canon_of(r["raw_model_name"])].append(r["price_usd"])
    lowest_in = {c: min(v) for c, v in price_by_model.items() if len(set(v)) >= 2 and len(v) >= 2}
    price_by_model_out: dict[str, list[float]] = defaultdict(list)
    for r in recs:
        if r["unit"] == UNIT_OUT:
            price_by_model_out[canon_of(r["raw_model_name"])].append(r["price_usd"])
    lowest_out = {c: min(v) for c, v in price_by_model_out.items() if len(set(v)) >= 2 and len(v) >= 2}

    groups = defaultdict(list)
    for r in recs:
        groups[r["provider_id"]].append(r)

    providers, model_rows = [], []
    for pid, rs in groups.items():
        f = rs[0]
        home, meta = station_home(f["provider_name"])
        if pid in HOME_OVERRIDES:
            home = HOME_OVERRIDES[pid]
        models = {r["raw_model_name"] for r in rs}
        low_by_canon: dict[str, float] = {}
        or_by_canon: dict[str, float] = {}
        price_by_canon: dict[str, float] = {}
        outliers = 0

        for r in rs:
            if r["unit"] != UNIT_IN:
                continue
            c = canon_of(r["raw_model_name"])
            low = lowest_in.get(c)
            if low and low > 0:
                ratio = r["price_usd"] / low
                # 同站同名模型去重：取最低倍率
                if c not in low_by_canon or ratio < low_by_canon[c]:
                    low_by_canon[c] = ratio
                    price_by_canon[c] = r["price_usd"]
                if ratio > MAX_RATIO:
                    outliers += 1
            b = base_in.get(c)
            if b and b > 0:
                or_by_canon[c] = r["price_usd"] / b

        # 极端倍率（疑似单位错误/异常报价）不计入中位数
        clean = {c: v for c, v in low_by_canon.items() if v <= MAX_RATIO}
        ratio_in = pick_ratio(list(clean.values()))
        ratio_or = pick_ratio(list(or_by_canon.values()))

        detail = []
        if pid != BASELINE:
            for c, ratio in clean.items():
                detail.append({"model": c, "ratio": ratio, "price": price_by_canon[c],
                               "tier": tiers.get(c, 9)})
        # 代表模型：主力档（tier>=2）里倍率最低的
        main = [d for d in detail if d["tier"] >= 2] or detail
        best = min(main, key=lambda d: d["ratio"]) if main else None

        source_urls = sorted({r.get("source_url") for r in rs if r.get("source_url")})
        providers.append({
            "provider_id": pid,
            "provider_name": f["provider_name"],
            "channel_type": meta.get("type") or f.get("channel_type"),
            "status": meta.get("status"),
            "model_count": len(models),
            "record_count": len(rs),
            "ratio_in": ratio_in,
            "ratio_or": ratio_or,
            "samples": len(clean),
            "outliers": outliers,
            "best_model": best["model"] if best else None,
            "best_ratio": round(best["ratio"], 4) if best else None,
            "best_price": round(best["price"], 4) if best else None,
            "home_url": home,
            "source_url": source_urls[0] if source_urls else None,
            "source_urls": source_urls,
            "captured_at": (f.get("captured_at") or "")[:19],
        })

    # 排序：有倍率的按倍率升序（性价比高在前），无倍率的按模型数
    providers.sort(key=lambda p: (p["ratio_in"] is None, p["ratio_in"] or 0, -p["model_count"]))

    # 模型比价：以 canonical 聚合，列出各站报价与相对全网最低价倍率
    by_model = defaultdict(list)
    for r in recs:
        if r["unit"] != UNIT_IN:
            continue
        c = canon_of(r["raw_model_name"])
        low = lowest_in.get(c)
        if not low:
            continue
        by_model[c].append({
            "provider": r["provider_name"],
            "raw": r["raw_model_name"],
            "price": r["price_usd"],
            "ratio": round(r["price_usd"] / low, 4),
            "is_base": r["provider_id"] == BASELINE,
            "tier": tiers.get(c, 9),
        })
    for model, offers in by_model.items():
        offers.sort(key=lambda o: o["price"])
        # 同站多名称映射到同一 canonical 时，只保留最低价那条
        seen, dedup = set(), []
        for o in offers:
            if o["provider"] in seen:
                continue
            seen.add(o["provider"])
            dedup.append(o)
        offers = dedup
        model_rows.append({
            "model": model,
            "tier": offers[0]["tier"],
            "base_price": round(base_in[model], 4) if base_in.get(model) else None,
            "min_price": offers[0]["price"],
            "count": len(offers),
            "offers": offers[:10],
        })
    model_rows = [m for m in model_rows if m["count"] >= 2]
    model_rows.sort(key=lambda m: (m["tier"], -m["count"]))
    return providers, model_rows[:60]


def esc(v) -> str:
    return html.escape(str(v))


def render(env: dict, providers: list, models: list, generated_at: str) -> str:
    prov_json = json.dumps(providers, ensure_ascii=False).replace("</", "<\\/")
    model_json = json.dumps(models, ensure_ascii=False).replace("</", "<\\/")
    snap = esc(env["snapshot_date"])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>API 中转站性价比榜 · rank.jiechuan1011.com</title>
<meta name="description" content="AI API 中转站实时价格与性价比排行，以 OpenRouter 实价为基准计算相对倍率，数据自动更新。">
<style>
:root {{ --bg:#0d1117; --card:#161b22; --border:#30363d; --fg:#e6edf3; --dim:#8b949e; --acc:#58a6ff; --good:#3fb950; --bad:#f85149; --warn:#d29922; }}
* {{ box-sizing:border-box; }}
body {{ font-family:system-ui,"Microsoft YaHei",sans-serif; margin:0; background:var(--bg); color:var(--fg); }}
.wrap {{ max-width:1180px; margin:0 auto; padding:2rem 1rem; }}
h1 {{ margin:0 0 .3rem; font-size:1.55rem; }}
.meta {{ color:var(--dim); font-size:.85rem; margin-bottom:1.2rem; line-height:1.7; }}
.meta a {{ color:var(--acc); }}
.tabs {{ display:flex; gap:.5rem; margin-bottom:1rem; flex-wrap:wrap; }}
.tabs button {{ background:var(--card); color:var(--dim); border:1px solid var(--border); padding:.45rem 1rem; border-radius:8px; cursor:pointer; font-size:.9rem; }}
.tabs button.on {{ color:var(--fg); border-color:var(--acc); }}
input#q {{ background:var(--card); color:var(--fg); border:1px solid var(--border); padding:.5rem .9rem; border-radius:8px; width:300px; font-size:.9rem; outline:none; }}
.legend {{ color:var(--dim); font-size:.8rem; margin:.6rem 0 0; }}
table {{ border-collapse:collapse; width:100%; font-size:.86rem; margin-top:.8rem; }}
th,td {{ border-bottom:1px solid var(--border); padding:.55rem .6rem; text-align:left; vertical-align:top; }}
th {{ color:var(--dim); font-weight:600; cursor:pointer; user-select:none; white-space:nowrap; position:sticky; top:0; background:var(--bg); }}
th.num,td.num {{ text-align:right; }}
tr:hover td {{ background:#1c2129; }}
td a {{ color:var(--acc); text-decoration:none; }}
td a:hover {{ text-decoration:underline; }}
.ratio {{ font-weight:600; }}
.cheap {{ color:var(--good); }}
.mid {{ color:var(--fg); }}
.expensive {{ color:var(--bad); }}
.na {{ color:var(--dim); }}
.tag {{ display:inline-block; background:#1f6feb22; color:var(--acc); border-radius:9px; padding:.02rem .45rem; font-size:.72rem; margin-left:.3rem; }}
.tag.inactive {{ background:#f8514922; color:var(--bad); }}
.model-card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.9rem 1.1rem; margin-bottom:.8rem; }}
.model-card h3 {{ margin:0 0 .5rem; font-size:.95rem; word-break:break-all; }}
.base {{ color:var(--dim); font-size:.8rem; font-weight:400; margin-left:.5rem; }}
table.mini {{ margin-top:.4rem; font-size:.82rem; }}
table.mini th {{ cursor:default; position:static; }}
.offers {{ display:flex; flex-wrap:wrap; gap:.4rem; }}
.offers span {{ background:#21262d; border:1px solid var(--border); border-radius:6px; padding:.15rem .5rem; font-size:.78rem; }}
.offers span.best {{ border-color:var(--good); color:var(--good); }}
.src {{ color:var(--dim); font-size:.8rem; margin-top:2rem; line-height:1.7; }}
</style>
</head>
<body>
<div class="wrap">
<h1>🛰️ API 中转站性价比榜</h1>
<p class="meta">
 数据快照 {snap} · {len(providers)} 个站点 · {env["record_count"]} 条价格记录 ·
 性价比基准 = 全网同模型最低价 ·
 来源 <a href="https://github.com/howardpen9/awesome-ai-api-proxy" target="_blank" rel="noopener">awesome-ai-api-proxy</a> ·
 生成于 {esc(generated_at)} UTC
</p>
<div class="tabs">
 <button id="tab-prov" class="on" onclick="show('prov')">性价比排行</button>
 <button id="tab-model" onclick="show('model')">模型比价</button>
</div>
<input id="q" placeholder="搜索站点 / 模型…" oninput="render()">
<p class="legend">性价比倍率 = 本站价格 ÷ 全网同模型最低价。<b class="cheap">1.00x</b> 即全网最低；<b class="expensive">2.00x</b> 表示同款模型贵一倍。「vs OpenRouter」列作为官方价参考对照。</p>

<div id="view-prov"><table id="tbl"><thead><tr>
 <th data-k="rank">#</th><th data-k="provider_name">站点</th><th data-k="channel_type">类型</th>
 <th data-k="model_count" class="num">模型数</th>
 <th data-k="ratio_in" class="num">性价比倍率</th><th data-k="ratio_or" class="num">vs OpenRouter</th>
 <th data-k="samples" class="num">可比样本</th>
 <th data-k="best_ratio">最划算模型</th>
 <th>数据出处</th>
</tr></thead><tbody></tbody></table></div>

<div id="view-model" style="display:none"></div>

<p class="src">
 ⚠ 本站聚合公开价格数据，倍率基于各站公开挂牌价计算，仅供选站参考，不构成对任何站点的背书；实际价格与可用性以各站官网为准。<br>
 注意：部分站点在挂牌价基础上另有分组折扣，实际扣费可能更低。数据每 6 小时自动更新 · 每条记录保留原始出处（source_url / captured_at）·
 <a href="https://github.com/jiechuan1011/relay-benchmark" target="_blank" rel="noopener">GitHub 仓库</a>
</p>
</div>
<script>
const PROV = {prov_json};
const MODELS = {model_json};
let tab='prov', sortK='rank', sortAsc=true;

function esc(s) {{ const d=document.createElement('div'); d.textContent=s; return d.innerHTML; }}
function fmtRatio(v) {{
  if (v == null) return '<span class="na">—</span>';
  const cls = v <= 1.05 ? 'cheap' : (v > 1.5 ? 'expensive' : 'mid');
  return `<span class="ratio ${{cls}}">${{v.toFixed(2)}}x</span>`;
}}
function fmtPrice(v) {{ return v == null ? '—' : '$' + v.toFixed(3); }}

function show(t) {{
  tab=t;
  document.getElementById('view-prov').style.display = t==='prov'?'':'none';
  document.getElementById('view-model').style.display = t==='model'?'':'none';
  document.getElementById('tab-prov').classList.toggle('on', t==='prov');
  document.getElementById('tab-model').classList.toggle('on', t==='model');
  render();
}}

function render() {{
  const q = document.getElementById('q').value.toLowerCase().trim();
  if (tab === 'prov') {{
    let rows = PROV.map((p,i)=>({{...p, rank:i+1}}));
    if (q) rows = rows.filter(p => (p.provider_name+' '+(p.channel_type||'')).toLowerCase().includes(q));
    rows.sort((a,b) => {{
      const va=a[sortK], vb=b[sortK];
      if (va==null) return 1; if (vb==null) return -1;
      return (typeof va==='number' ? va-vb : String(va).localeCompare(String(vb))) * (sortAsc?1:-1);
    }});
    document.querySelector('#tbl tbody').innerHTML = rows.map(p => {{
      const name = p.home_url
        ? `<a href="${{esc(p.home_url)}}" target="_blank" rel="noopener">${{esc(p.provider_name)}}</a>`
        : esc(p.provider_name);
      const statusTag = (p.status === 'inactive') ? '<span class="tag inactive">已停用</span>'
        : (p.status === 'unverified' ? '<span class="tag">未验证</span>' : '');
      const best = p.best_model
        ? `<span class="na">${{esc(p.best_model)}}</span><br><b>${{fmtPrice(p.best_price)}}</b> · ${{fmtRatio(p.best_ratio)}}`
        : '<span class="na">基准站</span>';
      const src = p.source_url
        ? `<a href="${{esc(p.source_url)}}" target="_blank" rel="noopener">原始价格页</a>`
        : '<span class="na">—</span>';
      return `<tr>
        <td>${{p.rank}}</td>
        <td>${{name}}${{statusTag}}</td>
        <td>${{esc(p.channel_type||'—')}}</td>
        <td class="num">${{p.model_count}}</td>
        <td class="num">${{fmtRatio(p.ratio_in)}}</td>
        <td class="num">${{fmtRatio(p.ratio_or)}}</td>
        <td class="num">${{p.samples}}</td>
        <td>${{best}}</td>
        <td>${{src}}</td></tr>`;
    }}).join('');
  }} else {{
    let ms = MODELS.filter(m => !q || m.model.toLowerCase().includes(q));
    document.getElementById('view-model').innerHTML = ms.map(m => `<div class="model-card">
      <h3>${{esc(m.model)}}<span class="base">${{m.base_price ? 'OpenRouter ' + fmtPrice(m.base_price) : 'OR 无报价'}} · 最低 ${{fmtPrice(m.min_price)}} / 1M · ${{m.count}} 家报价</span></h3>
      <div class="offers">${{m.offers.map((o,i)=>`<span class="${{i===0?'best':''}}">${{esc(o.provider)}} ${{fmtPrice(o.price)}} (${{o.ratio.toFixed(2)}}x)</span>`).join('')}}</div>
    </div>`).join('') || '<p class="meta">无匹配模型</p>';
  }}
}}

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
    env = json.loads(fetch(UPSTREAM_PRICES).decode("utf-8"))
    providers_yaml = fetch(UPSTREAM_PROVIDERS).decode("utf-8", "replace")
    canonical_yaml = fetch(UPSTREAM_CANONICAL).decode("utf-8", "replace")

    providers, models = build(env, providers_yaml, canonical_yaml)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    DIST.mkdir(exist_ok=True)
    (DIST / "index.html").write_text(render(env, providers, models, generated_at), encoding="utf-8")
    (DIST / "data").mkdir(exist_ok=True)
    (DIST / "data" / "providers.json").write_text(
        json.dumps({"snapshot_date": env["snapshot_date"], "generated_at": generated_at,
                    "baseline": "OpenRouter", "providers": providers},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "data" / "models.json").write_text(
        json.dumps({"snapshot_date": env["snapshot_date"], "models": models},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    (DIST / "data" / "prices.latest.json").write_text(json.dumps(env, ensure_ascii=False), encoding="utf-8")
    (DIST / "CNAME").write_text("rank.jiechuan1011.com\n", encoding="utf-8")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")

    print(f"OK: {len(providers)} providers, {len(models)} comparable models, {env['record_count']} records")
    for p in providers:
        print(f"  {p['provider_name']:<22} low={p['ratio_in']} or={p['ratio_or']} n={p['samples']} url={p['home_url']}")


if __name__ == "__main__":
    main()
