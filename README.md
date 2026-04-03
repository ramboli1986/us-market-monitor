# 美股市场监控中心

实时财经新闻 · 财经日历 · 影响大盘的关键因素分析

## 功能

- 📅 **财经日历**：2026年全年 FOMC 会议、CPI/NFP/PCE 等经济数据发布日期、七巨头财报日期
- 📡 **实时新闻**：来自 CNBC 的财经新闻，自动翻译为中文，每小时更新
- 📊 **影响因素分析**：货币政策、经济数据、地缘政治等对美股的影响分析
- 💼 **财报季**：科技七巨头及主要银行财报时间表
- 🔭 **综合概览**：影响力雷达图和排行榜

## 技术架构

```
GitHub Actions (每小时)
    → scripts/fetch_news.py
        → 抓取 CNBC RSS (4个频道)
        → MyMemory API 免费翻译
        → 生成 public/news.json
    → git commit & push
        → Vercel 自动重新部署
            → 用户访问静态网页
            → 浏览器读取 /news.json
```

## 本地开发

```bash
# 手动抓取新闻
python3 scripts/fetch_news.py

# 本地预览
cd public && python3 -m http.server 8080
```

## 部署

本项目通过 Vercel 自动部署，连接此 GitHub 仓库即可。
GitHub Actions 每小时自动更新 `public/news.json`，Vercel 检测到推送后自动重新部署。
