import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


WEEKDAYS = "一二三四五六日"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
CITY_COORDS = {
    "北京": (39.9042, 116.4074),
    "合肥": (31.8206, 117.2272),
    "洛阳": (34.6197, 112.4540),
}
# WMO 天气代码 -> 国内天气预报常用说法
WMO_WEATHER = {
    0: "晴",
    1: "晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾",
    51: "小雨",
    53: "小雨",
    55: "小雨",
    56: "冻雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "小雪",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴冰雹",
    99: "雷阵雨伴冰雹",
}
# 蒲福风级下限（m/s），下标即风级
BEAUFORT_MS = [0, 0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7]
# HJ 633-2012 环境空气质量指数分段（24 小时平均；O3 为 8 小时滑动平均，CO 单位 mg/m³）
IAQI_STEPS = [0, 50, 100, 150, 200, 300, 400, 500]
AQI_BREAKPOINTS = {
    "pm2_5": [0, 35, 75, 115, 150, 250, 350, 500],
    "pm10": [0, 50, 150, 250, 350, 420, 500, 600],
    "sulphur_dioxide": [0, 50, 150, 475, 800, 1600, 2100, 2620],
    "nitrogen_dioxide": [0, 40, 80, 180, 280, 565, 750, 940],
    "carbon_monoxide": [0, 2, 4, 14, 24, 36, 48, 60],
    "ozone": [0, 100, 160, 215, 265, 800],
}
AQI_LEVELS = [(50, "优"), (100, "良"), (150, "轻度污染"), (200, "中度污染"), (300, "重度污染")]
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
        "title": "国际",
        "count": 6,
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
        "title": "国内",
        "count": 6,
    },
    "河南·洛阳": {
        "rss": [
            ("中新网河南", "https://www.chinanews.com.cn/rss/china.xml"),
        ],
        # 地方站整站都是本地新闻，不按关键词过滤；洛阳网、大河网对脚本访问一律返回 403，不再使用
        "html": [
            ("洛阳市政府网", "https://www.ly.gov.cn/"),
            ("人民网河南", "http://henan.people.com.cn/"),
            ("新华网河南", "http://www.ha.news.cn/"),
            ("中新网河南", "https://www.ha.chinanews.com.cn/"),
        ],
        "keywords": ["洛阳", "河南"],
        "per_source": 4,
        "hint": "优先选洛阳本地新闻，其次是河南全省的重要新闻",
        "title": "河南 · 洛阳",
        "count": 4,
    },
    "AI科技": {
        "rss": [
            ("量子位", "https://www.qbitai.com/feed"),
            ("IT之家", "https://www.ithome.com/rss/"),
            ("爱范儿", "https://www.ifanr.com/feed"),
        ],
        "html": [],
        "keywords": [
            "AI", "人工智能", "大模型", "模型", "智能体", "算力", "芯片", "机器人", "具身",
            "自动驾驶", "OpenAI", "DeepSeek", "ChatGPT", "GPT", "Gemini", "Claude", "英伟达",
        ],
        "per_source": 6,
        "hint": "聚焦 AI 与前沿科技，优先选大模型、芯片算力、重要产品发布和行业动向，避开纯营销稿",
        "title": "AI 科技",
        "count": 4,
    },
}
# 企业微信单条 markdown 上限 4096 字节，放不下全部板块，新闻拆成两条连续发送
NEWS_MESSAGES = [
    ("早间新闻", ["国际", "中国"]),
    ("本地 · 科技", ["河南·洛阳", "AI科技"]),
]
# 写入消息文件的分隔行，send_wechat.py 按它拆成多条消息依次发送
MESSAGE_BREAK = "<!-- message-break -->"
# 只保留发布日期在这么多天以内的文章（HTML 看 URL 中的日期，RSS 看 pubDate），过滤导航链接和旧闻
NEWS_MAX_AGE_DAYS = 1
# 消息里展示的简短来源名
SOURCE_SHORT_NAMES = {
    "中国新闻网国际": "中新网",
    "中国新闻网时政": "中新网",
    "中国新闻网要闻": "中新网",
    "人民网国际": "人民网",
    "人民网时政": "人民网",
    "洛阳市政府网": "洛阳市政府网",
    "人民网河南": "人民网河南",
    "新华网河南": "新华网河南",
    "中新网河南": "中新网河南",
    "量子位": "量子位",
    "IT之家": "IT之家",
    "爱范儿": "爱范儿",
}
ALLOWED_NEWS_DOMAINS = (
    "chinanews.com.cn",
    "people.com.cn",
    "news.cn",
    "ly.gov.cn",
    "qbitai.com",
    "ithome.com",
    "ifanr.com",
)


def beijing_now():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def date_line(now):
    return f"{now.month}月{now.day}日 星期{WEEKDAYS[now.weekday()]}"


def fetch_json(url, params, retries=2):
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{url}?{query}",
        headers={"User-Agent": "yue-weather-relay/1.0"},
    )
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                wait_seconds = 5 * (attempt + 1)
                print(f"Fetch failed for {url}: {exc}; retrying in {wait_seconds}s.", file=sys.stderr)
                time.sleep(wait_seconds)
                continue
            raise SystemExit(f"Failed to fetch {url}: {exc}") from exc


def detect_charset(header_charset, raw):
    # 不少地方新闻站是 GBK 编码，按 UTF-8 解码会得到乱码标题
    charset = header_charset
    if not charset:
        match = re.search(rb"""<meta[^>]+charset=["']?([\w-]+)""", raw[:4096], re.IGNORECASE)
        charset = match.group(1).decode("ascii") if match else "utf-8"
    charset = charset.lower()
    if charset in ("gb2312", "gbk"):
        return "gb18030"
    return charset


def fetch_text(url, retries=2):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "yue-weather-relay/1.0"},
    )
    last_error = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return raw.decode(detect_charset(resp.headers.get_content_charset(), raw), errors="replace")
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
        return ""
    directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
    return directions[round(float(degrees) / 45) % 8]


def wind_text(degrees, speed_kmh):
    if speed_kmh is None:
        return "风力暂无数据"
    speed_ms = float(speed_kmh) / 3.6
    level = max(i for i, low in enumerate(BEAUFORT_MS) if speed_ms >= low)
    if level <= 1:
        return "微风"
    return f"{wind_direction(degrees)}风 {level}级"


def weather_name(code):
    if code is None:
        return "暂无数据"
    return WMO_WEATHER.get(int(code), "暂无数据")


def first(values):
    return (values or [None])[0]


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def max_rolling_mean(values, window):
    values = [value for value in values if value is not None]
    if len(values) < window:
        return mean(values)
    return max(sum(values[i:i + window]) / window for i in range(len(values) - window + 1))


def iaqi(pollutant, concentration):
    breakpoints = AQI_BREAKPOINTS[pollutant]
    if concentration >= breakpoints[-1]:
        return IAQI_STEPS[len(breakpoints) - 1]
    for i in range(1, len(breakpoints)):
        if concentration <= breakpoints[i]:
            low, high = breakpoints[i - 1], breakpoints[i]
            return IAQI_STEPS[i - 1] + (IAQI_STEPS[i] - IAQI_STEPS[i - 1]) * (concentration - low) / (high - low)
    return IAQI_STEPS[len(breakpoints) - 1]


def china_aqi(hourly):
    concentrations = {
        "pm2_5": mean(hourly.get("pm2_5", [])),
        "pm10": mean(hourly.get("pm10", [])),
        "sulphur_dioxide": mean(hourly.get("sulphur_dioxide", [])),
        "nitrogen_dioxide": mean(hourly.get("nitrogen_dioxide", [])),
        "ozone": max_rolling_mean(hourly.get("ozone", []), 8),
    }
    carbon_monoxide = mean(hourly.get("carbon_monoxide", []))
    concentrations["carbon_monoxide"] = carbon_monoxide / 1000 if carbon_monoxide is not None else None

    values = [iaqi(name, value) for name, value in concentrations.items() if value is not None]
    if not values:
        return None
    return math.ceil(max(values))


def aqi_level(aqi):
    for limit, level in AQI_LEVELS:
        if aqi <= limit:
            return level
    return "严重污染"


def fetch_city_weather(city, lat, lon):
    forecast = fetch_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_direction_10m_dominant,precipitation_probability_max",
            "forecast_days": 1,
            "timezone": "Asia/Shanghai",
        },
    )
    air = fetch_json(
        "https://air-quality-api.open-meteo.com/v1/air-quality",
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "pm2_5,pm10,sulphur_dioxide,nitrogen_dioxide,carbon_monoxide,ozone",
            "forecast_days": 1,
            "timezone": "Asia/Shanghai",
        },
    )

    daily = forecast.get("daily", {})
    low = first(daily.get("temperature_2m_min"))
    high = first(daily.get("temperature_2m_max"))
    aqi = china_aqi(air.get("hourly", {}))
    return {
        "city": city,
        "weather": weather_name(first(daily.get("weather_code"))),
        "low": round(low) if low is not None else None,
        "high": round(high) if high is not None else None,
        "wind": wind_text(first(daily.get("wind_direction_10m_dominant")), first(daily.get("wind_speed_10m_max"))),
        "rain_chance": first(daily.get("precipitation_probability_max")),
        "aqi": aqi,
        "aqi_level": aqi_level(aqi) if aqi is not None else None,
    }


def weather_facts(cities):
    lines = []
    for item in cities:
        lines.append(
            f"{item['city']}：{item['weather']}，{item['low']}~{item['high']}°C，{item['wind']}，"
            f"降水概率 {item['rain_chance']}%，空气 {item['aqi_level'] or '暂无数据'}"
            + (f"（AQI {item['aqi']}）" if item["aqi"] is not None else "")
        )
    return "\n".join(lines)


def fallback_weather_tip(cities):
    tips = []
    polluted = [item["city"] for item in cities if item["aqi"] is not None and item["aqi"] > 150]
    rainy = [item["city"] for item in cities if "雨" in item["weather"] or "雪" in item["weather"]]
    if polluted:
        tips.append(f"{'、'.join(polluted)}空气污染较重，尽量减少户外活动")
    if rainy:
        tips.append(f"{'、'.join(rainy)}有降水，出门记得带伞")
    if not tips:
        tips.append("三地天气平稳，早晚温差较大，注意适时增减衣物")
    return "；".join(tips) + "。"


def generate_weather_tip(cities, model):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是天气预报编辑，只根据给定数据写提示，不编造信息。"},
            {
                "role": "user",
                "content": (
                    "根据下面三城今天的天气，写一句早间出行与穿衣提示，60 字以内，"
                    "突出最值得注意的情况（污染、降水、大风、降温等），纯文本，不要 markdown、不要 emoji。\n\n"
                    f"{weather_facts(cities)}"
                ),
            },
        ],
        "stream": False,
        "temperature": 0.3,
        "max_tokens": 200,
        "thinking": {"type": "disabled"},
    }
    try:
        tip = extract_output_text(deepseek_request(payload)).strip()
    except SystemExit as exc:
        print(f"Weather tip generation failed, using fallback: {exc}", file=sys.stderr)
        tip = ""
    return " ".join(tip.split()) or fallback_weather_tip(cities)


def render_weather(now, cities, tip):
    lines = [
        "# 天气早报",
        f'<font color="comment">{date_line(now)}　{" · ".join(item["city"] for item in cities)}</font>',
        "",
    ]
    for item in cities:
        if item["low"] is None or item["high"] is None:
            temperature = "暂无数据"
        else:
            temperature = f'<font color="info">{item["low"]}° ~ {item["high"]}°</font>'
        if item["aqi"] is None:
            air = "空气 暂无数据"
        elif item["aqi"] > 150:
            air = f'空气 <font color="warning">{item["aqi_level"]} {item["aqi"]}</font>'
        else:
            air = f"空气 {item['aqi_level']} {item['aqi']}"
        lines.extend(
            [
                f"> **{item['city']}**　{item['weather']}　{temperature}",
                f"> {item['wind']}　{air}",
                "",
            ]
        )
    lines.extend(
        [
            f"**今日提示**　{tip}",
            '<font color="comment">数据来源 Open-Meteo · 空气质量按国标 HJ 633 估算</font>',
        ]
    )
    return "\n".join(lines)


def build_weather_message(model):
    now = beijing_now()
    cities = [fetch_city_weather(city, lat, lon) for city, (lat, lon) in CITY_COORDS.items()]
    return render_weather(now, cities, generate_weather_tip(cities, model))


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
    if "utm_source=" in url:
        url = url.split("?", 1)[0]
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


def rss_date(published):
    if not published:
        return None
    try:
        return parsedate_to_datetime(published).astimezone(ZoneInfo("Asia/Shanghai")).date()
    except (TypeError, ValueError):
        pass
    match = re.match(r"(20\d\d)-(\d\d)-(\d\d)", published)
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups())).date()
    except ValueError:
        return None


def fetch_rss_articles(feeds, keywords=None, max_records=18, per_source=None):
    articles = []
    seen = set()
    today = beijing_now().date()
    for source, feed_url in feeds:
        source_count = 0
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
            # 没有可解析日期的条目保留，只剔除明确过期的
            published_date = rss_date(published)
            if published_date is not None and not is_fresh(published_date, today):
                continue
            article = normalize_article(title, url, source, published, keywords)
            if not article or article["url"] in seen:
                continue
            seen.add(article["url"])
            articles.append(article)
            source_count += 1
            if len(articles) >= max_records:
                return articles
            if per_source and source_count >= per_source:
                break
    return articles


def url_date(url):
    # 新闻站文章 URL 里通常带日期：/2026/10-23/、/20261023/、/2026/1024/
    match = re.search(r"/(20\d\d)[/-]?(\d\d)[/-]?(\d\d)/", url)
    if not match:
        return None
    try:
        return datetime(*map(int, match.groups())).date()
    except ValueError:
        return None


def is_fresh(published, today):
    return 0 <= (today - published).days <= NEWS_MAX_AGE_DAYS


def is_recent(url, today):
    published = url_date(url)
    return published is not None and is_fresh(published, today)


def fetch_html_articles(feeds, keywords=None, max_records=18, per_source=None):
    articles = []
    seen = set()
    today = beijing_now().date()
    for source, page_url in feeds:
        source_count = 0
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
            if not is_recent(url, today):
                continue
            article = normalize_article(title, url, source, keywords=keywords)
            if not article or article["url"] in seen:
                continue
            seen.add(article["url"])
            articles.append(article)
            source_count += 1
            if len(articles) >= max_records:
                return articles
            if per_source and source_count >= per_source:
                break
    return articles


def fetch_news_articles(section, max_records=18):
    config = NEWS_SECTIONS[section]
    keywords = config["keywords"]
    articles = fetch_rss_articles(
        config["rss"],
        keywords=keywords,
        max_records=max_records,
        per_source=config.get("per_source"),
    )
    source_parts = []
    if articles:
        source_parts.append("RSS")

    if len(articles) < max_records:
        html_articles = fetch_html_articles(
            config["html"],
            max_records=max_records - len(articles),
            per_source=config.get("per_source"),
        )
        existing_urls = {article["url"] for article in articles}
        for article in html_articles:
            if article["url"] not in existing_urls:
                articles.append(article)
                existing_urls.add(article["url"])
        if html_articles:
            source_parts.append("HTML")

    return "+".join(source_parts) if source_parts else "unavailable", articles[:max_records]




def collect_news_candidates():
    sections = []
    next_id = 1
    for name, config in NEWS_SECTIONS.items():
        source, articles = fetch_news_articles(name, max_records=16)
        candidates = []
        for article in articles:
            candidates.append(dict(article, id=next_id))
            next_id += 1
        print(f"News section {name}: {len(candidates)} candidates via {source}.", file=sys.stderr)
        sections.append((name, candidates))

    if not any(candidates for _, candidates in sections):
        raise SystemExit("No news articles fetched from mainland Chinese news sources.")
    return sections


def build_news_prompt(now, sections):
    blocks = []
    for name, candidates in sections:
        hint = NEWS_SECTIONS[name].get("hint")
        lines = [f"【{name}】最多选 {NEWS_SECTIONS[name]['count']} 条" + (f"，{hint}" if hint else "")]
        for article in candidates:
            lines.append(f"{article['id']}. {article['title']}（{article['source']}）")
        if not candidates:
            lines.append("（无候选）")
        blocks.append("\n".join(lines))

    item_format = '{"id": 编号, "title": "标题", "summary": "要点"}'
    section_format = ", ".join(f'"{name}": [{item_format}, ...]' for name, _ in sections)
    return f"""
今天是北京时间 {now:%Y-%m-%d} 星期{WEEKDAYS[now.weekday()]}。
下面是按板块分好的候选新闻，每条前面是编号。请为每个板块挑出最重要的新闻，写成早间新闻简报。

{chr(10).join(blocks)}

只输出 JSON，格式：
{{"sections": {{{section_format}}}, "observation": "今日观察"}}

要求：
- 只能使用上面列出的编号，不能选编号以外的新闻；同一事件只选一条。
- 优先选重要、有实际影响的事件，避开娱乐八卦；板块没有合适新闻就给空数组，不要凑数。
- title：在原标题基础上精炼到 22 字以内，不改变事实，不加引号和书名号以外的符号。
- summary：一句话补充标题没说清的关键信息，15 到 30 字，不要重复标题，不编造人物、日期、数字。
- observation：一句话点出今天新闻的主线，40 字以内。
- 全部使用中文，不要 emoji，不要 markdown。
""".strip()


def parse_news_selection(text, sections):
    try:
        data = json.loads(clean_markdown(text))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"DeepSeek returned invalid JSON: {text[:500]}") from exc

    picked = []
    used_ids = set()
    selection = data.get("sections") or {}
    for name, candidates in sections:
        by_id = {article["id"]: article for article in candidates}
        items = []
        for entry in selection.get(name) or []:
            try:
                article = by_id.get(int(entry.get("id")))
            except (TypeError, ValueError):
                article = None
            if not article or article["id"] in used_ids:
                continue
            used_ids.add(article["id"])
            items.append(
                {
                    "title": " ".join((entry.get("title") or article["title"]).split()),
                    "summary": " ".join((entry.get("summary") or "").split()),
                    "url": article["url"],
                    "source": SOURCE_SHORT_NAMES.get(article["source"], article["source"]),
                }
            )
            if len(items) >= NEWS_SECTIONS[name]["count"]:
                break
        picked.append((name, items))

    if not any(items for _, items in picked):
        raise SystemExit(f"DeepSeek selected no valid news: {text[:500]}")
    return picked, " ".join((data.get("observation") or "").split())


def render_news(now, heading, picked, observation):
    lines = [
        f"# {heading}",
        f'<font color="comment">{date_line(now)}</font>',
        "",
    ]
    for name, items in picked:
        if not items:
            continue
        lines.append(f"**{NEWS_SECTIONS[name]['title']}**")
        for item in items:
            title = item["title"].replace("[", "【").replace("]", "】")
            detail = f"{item['summary']} · {item['source']}" if item["summary"] else item["source"]
            lines.append(f"> [{title}]({item['url']})")
            lines.append(f'> <font color="comment">{detail}</font>')
        lines.append("")
    if observation:
        lines.extend(["**今日观察**", f'<font color="comment">{observation}</font>'])
    return "\n".join(lines).rstrip()


def fit_news(now, heading, picked, observation, max_bytes):
    picked = [(name, list(items)) for name, items in picked]
    text = render_news(now, heading, picked, observation)
    while len(text.encode("utf-8")) > max_bytes:
        # 从条目最多的板块末尾删一条，直到满足企业微信长度上限
        longest = max(picked, key=lambda section: len(section[1]))
        if not longest[1]:
            raise SystemExit(f"News message cannot fit in {max_bytes} bytes.")
        longest[1].pop()
        text = render_news(now, heading, picked, observation)
    return text


def compose_news(now, picked, observation, max_bytes):
    by_name = dict(picked)
    groups = []
    for heading, names in NEWS_MESSAGES:
        group = [(name, by_name.get(name, [])) for name in names]
        if any(items for _, items in group):
            groups.append((heading, group))

    # 今日观察放在最后一条消息末尾
    parts = []
    for index, (heading, group) in enumerate(groups):
        closing = observation if index == len(groups) - 1 else ""
        parts.append(fit_news(now, heading, group, closing, max_bytes))
    return f"\n\n{MESSAGE_BREAK}\n\n".join(parts)


def build_news_message(model, max_bytes):
    now = beijing_now()
    sections = collect_news_candidates()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是严谨的中文新闻编辑，只根据给定的候选新闻挑选和概括，不编造事实，只输出 JSON。",
            },
            {"role": "user", "content": build_news_prompt(now, sections)},
        ],
        "stream": False,
        "temperature": 0.2,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    text = extract_output_text(deepseek_request(payload))
    if not text:
        raise SystemExit("DeepSeek returned no text for news.")
    picked, observation = parse_news_selection(text, sections)
    return compose_news(now, picked, observation, max_bytes)


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
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"DeepSeek API request failed: {exc}") from exc


def main():
    kind = os.environ.get("MESSAGE_KIND", "").strip()
    output_file = os.environ.get("OUTPUT_FILE", "").strip()
    model = os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_MODEL
    max_bytes = int(os.environ.get("MAX_MESSAGE_BYTES", "3900"))

    if not output_file:
        raise SystemExit("Missing OUTPUT_FILE.")

    if kind == "weather":
        text = build_weather_message(model)
    elif kind == "news":
        text = build_news_message(model, max_bytes)
    else:
        raise SystemExit(f"Unsupported MESSAGE_KIND: {kind}")

    if not text.strip():
        raise SystemExit("Generated message is empty.")
    for part in text.split(MESSAGE_BREAK):
        if len(part.strip().encode("utf-8")) > max_bytes:
            raise SystemExit(f"Generated content is too long: {len(part.strip().encode('utf-8'))} bytes > {max_bytes} bytes.")

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
