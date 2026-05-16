import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime
from zoneinfo import ZoneInfo


WEEKDAYS = "一二三四五六日"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
CITY_COORDS = {
    "北京": (39.9042, 116.4074),
    "合肥": (31.8206, 117.2272),
    "洛阳": (34.6197, 112.4540),
}
WMO_WEATHER = {
    0: "晴",
    1: "基本晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "大毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}
NEWS_SECTIONS = {
    "国际": {
        "rss": [
            ("中国新闻网国际", "https://www.chinanews.com.cn/rss/world.xml"),
            ("人民网国际", "http://www.people.com.cn/rss/world.xml"),
        ],
        "html": [
            ("中国新闻网国际", "https://www.chinanews.com.cn/world/"),
            ("人民网国际", "https://world.people.com.cn/"),
        ],
        "keywords": [],
    },
    "中国": {
        "rss": [
            ("中国新闻网时政", "https://www.chinanews.com.cn/rss/china.xml"),
            ("中国新闻网要闻", "https://www.chinanews.com.cn/rss/importnews.xml"),
            ("人民网时政", "http://www.people.com.cn/rss/politics.xml"),
        ],
        "html": [
            ("中国新闻网时政", "https://www.chinanews.com.cn/china/"),
            ("人民网时政", "https://politics.people.com.cn/"),
        ],
        "keywords": [],
    },
    "河南·洛阳": {
        "rss": [
            ("中新网河南", "https://www.chinanews.com.cn/rss/china.xml"),
        ],
        "html": [
            ("洛阳网", "https://www.lyd.com.cn/"),
            ("洛阳网新闻", "https://news.lyd.com.cn/"),
            ("中新网河南", "https://www.ha.chinanews.com.cn/"),
        ],
        "keywords": ["洛阳", "河南"],
    },
}
ALLOWED_NEWS_DOMAINS = (
    "chinanews.com.cn",
    "people.com.cn",
    "lyd.com.cn",
    "ha.chinanews.com.cn",
)


def beijing_today():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.strftime("%Y-%m-%d"), f"星期{WEEKDAYS[now.weekday()]}"


def fetch_json(url, params):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "yue-weather-relay/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise SystemExit(f"Failed to fetch {url}: {exc}") from exc


def fetch_text(url, retries=2):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "yue-weather-relay/1.0"},
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429 and attempt < retries:
                wait_seconds = 2 ** attempt
                print(f"Rate limited by {url}; retrying in {wait_seconds}s.", file=sys.stderr)
                time.sleep(wait_seconds)
                continue
            break
        except urllib.error.URLError as exc:
            last_error = exc
            break
    raise last_error


class LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "").strip()
        if not href:
            return
        self.current_href = urllib.parse.urljoin(self.base_url, href)
        self.current_text = []

    def handle_data(self, data):
        if self.current_href:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self.current_href:
            return
        title = "".join(self.current_text).strip()
        if title:
            self.links.append((title, self.current_href))
        self.current_href = None
        self.current_text = []


def wind_direction(degrees):
    if degrees is None:
        return "暂无数据"
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return directions[round(float(degrees) / 45) % 8]


def weather_name(code):
    if code is None:
        return "暂无数据"
    return WMO_WEATHER.get(int(code), f"天气代码 {code}")


def aqi_level(aqi):
    if aqi is None:
        return "暂无可靠数据"
    aqi = int(round(float(aqi)))
    if aqi <= 50:
        level = "优"
    elif aqi <= 100:
        level = "良"
    elif aqi <= 150:
        level = "轻度污染"
    elif aqi <= 200:
        level = "中度污染"
    elif aqi <= 300:
        level = "重度污染"
    else:
        level = "严重污染"
    return f"AQI {aqi}（{level}）"


def build_weather_context():
    lines = [
        "数据源：Open-Meteo Forecast API 与 Open-Meteo Air Quality API。",
        "注意：该数据源不提供中国气象预警，预警请写“暂无明确预警”。",
    ]
    for city, (lat, lon) in CITY_COORDS.items():
        forecast = fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "current": "weather_code,temperature_2m,wind_speed_10m,wind_direction_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_direction_10m_dominant",
                "forecast_days": 1,
                "timezone": "Asia/Shanghai",
            },
        )
        air = fetch_json(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "us_aqi",
                "forecast_days": 1,
                "timezone": "Asia/Shanghai",
            },
        )

        daily = forecast.get("daily", {})
        hourly = air.get("hourly", {})
        aqi_values = [value for value in hourly.get("us_aqi", []) if value is not None]
        avg_aqi = sum(aqi_values) / len(aqi_values) if aqi_values else None

        lines.extend(
            [
                f"{city}:",
                f"- 天气：{weather_name((daily.get('weather_code') or [None])[0])}",
                f"- 温度：最低 {(daily.get('temperature_2m_min') or ['暂无数据'])[0]}°C / 最高 {(daily.get('temperature_2m_max') or ['暂无数据'])[0]}°C",
                f"- 风力：{wind_direction((daily.get('wind_direction_10m_dominant') or [None])[0])}风，最大风速 {(daily.get('wind_speed_10m_max') or ['暂无数据'])[0]} km/h",
                f"- 空气：{aqi_level(avg_aqi)}",
            ]
        )
    return "\n".join(lines)


def domain_allowed(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in ALLOWED_NEWS_DOMAINS)


def article_matches(title, keywords):
    if not keywords:
        return True
    return any(keyword in title for keyword in keywords)


def normalize_article(title, url, source, seen="", keywords=None):
    title = " ".join(title.split())
    url = url.strip()
    if len(title) < 6 or not url.startswith(("http://", "https://")):
        return None
    if not domain_allowed(url):
        return None
    if not article_matches(title, keywords or []):
        return None
    return {
        "title": title,
        "url": url,
        "source": source,
        "seen": seen,
    }


def fetch_rss_articles(feeds, keywords=None, max_records=18):
    articles = []
    seen = set()
    for source, feed_url in feeds:
        try:
            xml_text = fetch_text(feed_url, retries=1)
        except Exception as exc:
            print(f"RSS fetch failed for {source}: {exc}", file=sys.stderr)
            continue

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            print(f"RSS parse failed for {source}: {exc}", file=sys.stderr)
            continue

        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or item.findtext("published") or "").strip()
            article = normalize_article(title, url, source, published, keywords)
            if not article or article["url"] in seen:
                continue
            seen.add(article["url"])
            articles.append(article)
            if len(articles) >= max_records:
                return articles
    return articles


def fetch_html_articles(feeds, keywords=None, max_records=18):
    articles = []
    seen = set()
    for source, page_url in feeds:
        try:
            html_text = fetch_text(page_url, retries=1)
        except Exception as exc:
            print(f"HTML fetch failed for {source}: {exc}", file=sys.stderr)
            continue

        parser = LinkExtractor(page_url)
        try:
            parser.feed(html_text)
        except Exception as exc:
            print(f"HTML parse failed for {source}: {exc}", file=sys.stderr)
            continue

        for title, url in parser.links:
            article = normalize_article(title, url, source, keywords=keywords)
            if not article or article["url"] in seen:
                continue
            seen.add(article["url"])
            articles.append(article)
            if len(articles) >= max_records:
                return articles
    return articles


def fetch_news_articles(section, max_records=18):
    config = NEWS_SECTIONS[section]
    keywords = config["keywords"]
    articles = fetch_rss_articles(config["rss"], keywords=keywords, max_records=max_records)
    source_parts = []
    if articles:
        source_parts.append("RSS")

    if len(articles) < max_records:
        html_articles = fetch_html_articles(
            config["html"],
            keywords=keywords,
            max_records=max_records - len(articles),
        )
        existing_urls = {article["url"] for article in articles}
        for article in html_articles:
            if article["url"] not in existing_urls:
                articles.append(article)
                existing_urls.add(article["url"])
        if html_articles:
            source_parts.append("HTML")

    return "+".join(source_parts) if source_parts else "unavailable", articles[:max_records]


def build_news_context():
    sections = []
    for section in NEWS_SECTIONS:
        source, articles = fetch_news_articles(section, max_records=16)
        sections.append((section, source, articles))

    if not any(articles for _, _, articles in sections):
        raise SystemExit("No news articles fetched from mainland Chinese news sources.")

    def render(section, articles):
        lines = [section]
        for article in articles[:12]:
            lines.append(
                f"- {article['title']} | {article['url']} | {article['source']} | {article['seen']}"
            )
        return "\n".join(lines)

    source_line = "；".join(f"{section} {source}" for section, source, _ in sections)
    rendered_sections = [render(f"{section}候选新闻", articles) for section, _, articles in sections]
    return "\n\n".join(
        [f"数据源：{source_line}。所有链接必须来自中国大陆通常可访问的中文新闻网站，只能使用下列链接和标题，不得虚构链接。"]
        + rendered_sections
    )


def build_prompt(kind):
    today, weekday = beijing_today()

    if kind == "weather":
        context = build_weather_context()
        return f"""
今天是北京时间 {today} {weekday}。
请基于下面的数据源内容，生成北京、合肥、洛阳今天的天气、温度范围、风力、空气质量和气象预警。

{context}

只输出企业微信 markdown 正文，不要代码块，不要解释过程。格式必须类似：

# 今日三城天气速报
> {today} {weekday}

**北京**
- 天气：...
- 温度：最低 ... / 最高 ...
- 风力：...
- 空气：AQI ...（...）
- 预警：<font color="warning">...</font>

**合肥**
...

**洛阳**
...

---
**出行提示**：...

要求：
- 信息必须以北京时间今天为准。
- 不要添加数据源中没有的信息。
- 预警统一写“暂无明确预警”，除非数据源明确给出预警。
- 语言简洁，适合早上推送。
- 总长度控制在 1200 个中文字以内。
""".strip()

    if kind == "news":
        context = build_news_context()
        return f"""
今天是北京时间 {today} {weekday}。
请基于下面的候选新闻列表，生成一份面向中国用户的中文每日新闻速览，覆盖国际、中国、河南·洛阳三类新闻。

{context}

只输出企业微信 markdown 正文，不要代码块，不要解释过程。版式要清爽，适合微信群机器人阅读。格式必须类似：

# 早间新闻速览
> {today} {weekday}

**🌍 国际**
- [标题](链接) — 一句话说明。（来源）
- ...

**🇨🇳 中国**
- [标题](链接) — 一句话说明。（来源）
- ...

**📍 河南·洛阳**
- [标题](链接) — 一句话说明。（来源）
- ...

---
**一句话观察**：...

要求：
- 国际新闻 4 条，中国新闻 4 条，河南·洛阳 3 条；如果某类候选不足，可以少写，不要补虚假内容。
- 每条必须使用候选列表里的真实链接和来源名。
- 链接必须来自候选列表，不要使用 BBC、Al Jazeera、NPR、GDELT 等境外或聚合链接。
- 不要编造人物、日期、数字；如果标题信息不足，就只做谨慎概括。
- 语言要更贴近中国用户，标题可以轻微改写但不能改变事实。
- 总长度控制在 3900 字节以内，适合企业微信 markdown 机器人。
""".strip()

    raise SystemExit(f"Unsupported MESSAGE_KIND: {kind}")


def extract_output_text(response):
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return message.get("content") or ""


def clean_markdown(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def deepseek_request(payload):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY secret.")

    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"DeepSeek API error {exc.code}: {body}") from exc


def generate(kind, model):
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的中文信息整理助手。只根据用户提供的数据源写企业微信 markdown，不编造事实。",
            },
            {"role": "user", "content": build_prompt(kind)},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 1800,
        "thinking": {"type": "disabled"},
    }
    response = deepseek_request(payload)
    text = clean_markdown(extract_output_text(response))
    if not text:
        raise SystemExit(f"DeepSeek returned no text: {json.dumps(response, ensure_ascii=False)[:1000]}")
    return text


def shorten_if_needed(text, model, max_bytes):
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只负责压缩企业微信 markdown，不添加新事实。"},
            {
                "role": "user",
                "content": (
                    f"请把下面的企业微信 markdown 压缩到 {max_bytes} 字节以内。"
                    "保留标题、日期、主要条目和链接，不要代码块，不要解释。\n\n"
                    f"{text}"
                ),
            },
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 1400,
        "thinking": {"type": "disabled"},
    }
    response = deepseek_request(payload)
    shortened = clean_markdown(extract_output_text(response))
    if not shortened:
        raise SystemExit("DeepSeek returned no text while shortening content.")
    if len(shortened.encode("utf-8")) > max_bytes:
        raise SystemExit(
            f"Generated content is too long: {len(shortened.encode('utf-8'))} bytes > {max_bytes} bytes."
        )
    return shortened


def main():
    kind = os.environ.get("MESSAGE_KIND", "").strip()
    output_file = os.environ.get("OUTPUT_FILE", "").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL
    max_bytes = int(os.environ.get("MAX_MESSAGE_BYTES", "3900"))

    if not output_file:
        raise SystemExit("Missing OUTPUT_FILE.")

    text = shorten_if_needed(generate(kind, model), model, max_bytes)
    if not text.strip():
        raise SystemExit("Generated message is empty.")

    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")

    byte_count = len(text.encode("utf-8"))
    print(f"Generated {kind} message with DeepSeek {model}: {byte_count} bytes -> {output_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"generate_message.py failed: {exc}", file=sys.stderr)
        raise
