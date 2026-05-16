import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo


WEEKDAYS = "一二三四五六日"
DEFAULT_MODEL = "gpt-5-mini"


def beijing_today():
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.strftime("%Y-%m-%d"), f"星期{WEEKDAYS[now.weekday()]}"


def build_prompt(kind):
    today, weekday = beijing_today()

    if kind == "weather":
        return f"""
今天是北京时间 {today} {weekday}。
请使用联网搜索核对北京、合肥、洛阳今天的天气、温度范围、风力、空气质量和气象预警。

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
- 如果 AQI 或预警没有可靠来源，写“暂无可靠数据”或“暂无明确预警”。
- 语言简洁，适合早上推送。
- 总长度控制在 1200 个中文字以内。
""".strip()

    if kind == "news":
        return f"""
今天是北京时间 {today} {weekday}。
请使用联网搜索生成一份中文每日新闻速览，覆盖国际和中国新闻。

只输出企业微信 markdown 正文，不要代码块，不要解释过程。格式必须类似：

# 每日新闻速览
> {today} {weekday}

**国际**
- [标题](链接) — 一句话说明。（来源）
- ...

**中国**
- [标题](链接) — 一句话说明。（来源）
- ...

---
**今日观察**：...

要求：
- 尽量选择最近 24 小时内的重要新闻；如必须使用背景新闻，要明确是背景。
- 国际新闻 5 条，中国新闻 5 条。
- 每条必须有可打开的 markdown 链接和来源名。
- 不要编造人物、日期、数字、链接。
- 总长度控制在 3600 字节以内，适合企业微信 markdown 机器人。
""".strip()

    raise SystemExit(f"Unsupported MESSAGE_KIND: {kind}")


def extract_output_text(response):
    if isinstance(response.get("output_text"), str):
        return response["output_text"]

    chunks = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])

    return "\n".join(chunks)


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


def openai_request(payload):
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY secret.")

    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
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
        raise SystemExit(f"OpenAI API error {exc.code}: {body}") from exc


def generate(kind, model):
    payload = {
        "model": model,
        "input": build_prompt(kind),
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "medium",
                "user_location": {
                    "type": "approximate",
                    "country": "CN",
                    "city": "Shanghai",
                    "timezone": "Asia/Shanghai",
                },
            }
        ],
    }
    response = openai_request(payload)
    text = clean_markdown(extract_output_text(response))
    if not text:
        raise SystemExit(f"OpenAI returned no text: {json.dumps(response, ensure_ascii=False)[:1000]}")
    return text


def shorten_if_needed(text, model, max_bytes):
    if len(text.encode("utf-8")) <= max_bytes:
        return text

    payload = {
        "model": model,
        "input": (
            f"请把下面的企业微信 markdown 压缩到 {max_bytes} 字节以内。"
            "保留标题、日期、主要条目和链接，不要代码块，不要解释。\n\n"
            f"{text}"
        ),
    }
    response = openai_request(payload)
    shortened = clean_markdown(extract_output_text(response))
    if not shortened:
        raise SystemExit("OpenAI returned no text while shortening content.")
    if len(shortened.encode("utf-8")) > max_bytes:
        raise SystemExit(
            f"Generated content is too long: {len(shortened.encode('utf-8'))} bytes > {max_bytes} bytes."
        )
    return shortened


def main():
    kind = os.environ.get("MESSAGE_KIND", "").strip()
    output_file = os.environ.get("OUTPUT_FILE", "").strip()
    model = os.environ.get("OPENAI_MODEL", "").strip() or DEFAULT_MODEL
    max_bytes = int(os.environ.get("MAX_MESSAGE_BYTES", "3900"))

    if not output_file:
        raise SystemExit("Missing OUTPUT_FILE.")

    text = shorten_if_needed(generate(kind, model), model, max_bytes)
    if not text.strip():
        raise SystemExit("Generated message is empty.")

    with open(output_file, "w", encoding="utf-8") as handle:
        handle.write(text.rstrip() + "\n")

    byte_count = len(text.encode("utf-8"))
    print(f"Generated {kind} message with {model}: {byte_count} bytes -> {output_file}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"generate_message.py failed: {exc}", file=sys.stderr)
        raise
