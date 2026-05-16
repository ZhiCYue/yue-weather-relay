# yue-weather-relay

GitHub Actions 定时抓取天气/新闻源数据，调用 DeepSeek 生成 `weather.md` / `news.md`，发送到企业微信，并把生成内容提交回仓库。

## Required Secrets

- `DEEPSEEK_API_KEY`: DeepSeek API key，用于定时生成内容。
- `WECHAT_WEBHOOK`: 企业微信天气机器人 webhook。
- `WECHAT_WEBHOOK_NEWS`: 企业微信新闻机器人 webhook。

## Schedule

- 天气：每天北京时间 07:30。
- 新闻：每天北京时间 08:30。

GitHub Actions cron 使用 UTC，workflow 内注释已标出北京时间换算。

## News Sources

新闻生成只使用中国大陆通常可访问的中文来源：

- 中国新闻网
- 人民网
- 洛阳网
- 中新网河南

输出包含 `国际`、`中国`、`河南·洛阳` 三个板块。

## Optional Variables

- `DEEPSEEK_MODEL`: 默认使用 `deepseek-v4-flash`。
- `DEEPSEEK_BASE_URL`: 默认使用 `https://api.deepseek.com`。
