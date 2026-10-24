import json
import os
import sys
import hashlib
import time
import urllib.request


MESSAGE_BREAK = "<!-- message-break -->"


def append_summary(secret_name, message_file, content, response):
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return

    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("## WeChat Send\n\n")
        handle.write(f"- Secret: `{secret_name}`\n")
        handle.write(f"- Message file: `{message_file}`\n")
        handle.write(f"- Message bytes: `{len(content.encode('utf-8'))}`\n")
        handle.write(f"- Message sha256: `{digest}`\n")
        handle.write(f"- First line: `{first_line}`\n")
        handle.write(f"- WeChat response: `{response}`\n")


def main():
    webhook = os.environ.get("WEBHOOK", "").strip()
    message_file = os.environ.get("MESSAGE_FILE", "/tmp/msg.md").strip()
    secret_name = os.environ.get("WEBHOOK_SECRET_NAME", "WEBHOOK").strip()

    if not webhook:
        raise SystemExit(f"Missing {secret_name} secret.")

    with open(message_file, encoding="utf-8") as handle:
        content = handle.read()

    # 消息文件里可以用分隔行拆成多条，按顺序逐条发送
    parts = [part.strip() for part in content.split(MESSAGE_BREAK) if part.strip()]
    if not parts:
        raise SystemExit("Message content is empty.")

    for index, part in enumerate(parts):
        if index:
            time.sleep(1)
        payload = json.dumps(
            {"msgtype": "markdown", "markdown": {"content": part}},
            ensure_ascii=False,
        ).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=15).read().decode()
        print(resp)
        append_summary(secret_name, message_file, part, resp)
        data = json.loads(resp)
        if data.get("errcode") != 0:
            raise SystemExit(f"WeChat error on message {index + 1}/{len(parts)}: {resp}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"send_wechat.py failed: {exc}", file=sys.stderr)
        raise
