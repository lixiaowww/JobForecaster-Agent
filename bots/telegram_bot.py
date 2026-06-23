"""Telegram long-polling bot for crowd contributions."""
from __future__ import annotations

import os
import time

import requests

from bots.base import dispatch_command
from services.config_loader import load_config


def run_telegram_bot() -> None:
    token = os.environ.get(
        load_config().get("bots", {}).get("telegram", {}).get("token_env", "TELEGRAM_BOT_TOKEN"),
        "",
    ).strip()
    if not token:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN to run the Telegram bot")

    base = f"https://api.telegram.org/bot{token}"
    offset = 0
    print("[telegram] polling...")
    while True:
        resp = requests.get(
            f"{base}/getUpdates",
            params={"timeout": 30, "offset": offset},
            timeout=35,
        )
        resp.raise_for_status()
        for upd in resp.json().get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip()
            if not text.startswith("/"):
                continue
            chat_id = msg["chat"]["id"]
            user = msg.get("from", {})
            contributor_id = f"tg:{user.get('id', chat_id)}"
            parts = text.split(None, 1)
            command = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            try:
                reply = dispatch_command(contributor_id, command, args)
            except Exception as e:
                reply = f"❌ {e}"
            requests.post(
                f"{base}/sendMessage",
                json={"chat_id": chat_id, "text": reply},
                timeout=20,
            )
        time.sleep(0.5)


if __name__ == "__main__":
    run_telegram_bot()
