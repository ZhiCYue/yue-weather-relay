import json
import os
import sys
import urllib.request


def main():
    webhook = os.environ.get("WEBHOOK", "").strip()
    message_file = os.environ.get("MESSAGE_FILE", "/tmp/msg.md").strip()
    secret_name = os.environ.get("WEBHOOK_SECRET_NAME", "WEBHOOK").strip()

    if not webhook:
        raise SystemExit(f"Missing {secret_name} secret.")

    with open(message_file, encoding="utf-8") as handle:
        content = handle.read()

    if not content.strip():
        raise SystemExit("Message content is empty.")

    payload = json.dumps(
        {"msgtype": "markdown", "markdown": {"content": content}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=15).read().decode()
    print(resp)
    data = json.loads(resp)
    if data.get("errcode") != 0:
        raise SystemExit(f"WeChat error: {resp}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"send_wechat.py failed: {exc}", file=sys.stderr)
        raise
