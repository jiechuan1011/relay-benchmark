# API 中转站性价比榜 (rank.jiechuan1011.com)

聚合公开数据源的中转站价格榜，静态站生成器 + GitHub Pages 部署。

线上地址：<https://rank.jiechuan1011.com>

## 指标说明

| 指标 | 含义 |
|---|---|
| **性价比倍率** | 本站价格 ÷ 全网同模型最低价，取中位数。`1.00x` = 同款模型全网最低 |
| **vs OpenRouter** | 本站价格 ÷ OpenRouter 实价，取中位数。OpenRouter 价约等于官方价 +5%，可理解为「相对官方价的挂牌倍率」 |
| **可比样本** | 参与计算的模型数（仅统计至少两家站同时报价的模型） |
| **最划算模型** | 主力档模型中倍率最低的一个 |

只统计「≥2 家站同时报价」的模型，否则比值恒为 1 无意义；倍率 > 50x 的报价视为疑似单位/异常数据，不计入中位数。

⚠ 榜单基于各站**公开挂牌价**。部分站点（如 bltcy）挂牌价即官方价，实际折扣在分组倍率里，因此挂牌价会显得偏高。

## 数据来源

- [awesome-ai-api-proxy](https://github.com/howardpen9/awesome-ai-api-proxy)
  - `data/prices.latest.json` — 标准化价格记录（自带 `source_url` + `captured_at`）
  - `data/providers.yaml` — 站点元信息（官网、类型、状态）
  - `data/canonical-models.yaml` — 模型别名与分档

## 本地运行

```bash
python generate.py                    # 走 127.0.0.1:7890 代理
SKIP_PROXY=1 python generate.py       # 直连（CI 用）
python -m http.server -d dist         # 本地预览
```

零第三方依赖，仅标准库。

## 部署

推送到 `main` 后 GitHub Actions 自动构建并发布到 Pages；每 6 小时定时刷新一次数据。自定义域名 `rank.jiechuan1011.com`（Cloudflare 上 CNAME → `jiechuan1011.github.io`，需关闭橙云代理）。

## 路线图

- [x] L1 聚合层：上游价格数据接入 + 性价比倍率
- [ ] L2 自测层：自有探针实测（可用性 / 延迟 / 流式）
- [ ] L3 用户层：用户提交测试记录
