# API 中转站实时测评 (api.jiechuan1011.com)

聚合公开数据源的中转站价格/模型排行榜，静态站生成器 + GitHub Pages 部署。

## 数据来源

- [awesome-ai-api-proxy](https://github.com/howardpen9/awesome-ai-api-proxy) 的 `data/prices.latest.json`（每条记录自带 `source_url` + `captured_at`，本站逐条保留出处）

## 本地运行

```powershell
python generate.py   # 拉取上游数据并生成 dist/
# 预览 dist/index.html 或 python -m http.server -d dist
```

## 部署

推送到 GitHub 后，Actions 自动构建并发布到 GitHub Pages，绑定域名 `api.jiechuan1011.com`。

## 路线图

- [x] L1 聚合层：上游价格数据接入
- [ ] L2 自测层：自有探针实测（可用性/延迟/流式）
- [ ] L3 用户层：用户提交测试记录
