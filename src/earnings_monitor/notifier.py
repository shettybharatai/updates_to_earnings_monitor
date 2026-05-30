from __future__ import annotations

import logging
import os
from typing import Any, Dict

import requests


logger = logging.getLogger(__name__)


def send_telegram_message(config: Dict[str, Any], message: str) -> bool:
    bot_token = (
        config.get("telegram_bot_token")
        or config.get("TELEGRAM_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
    )
    chat_id = (
        config.get("telegram_chat_id")
        or config.get("TELEGRAM_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
    )

    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat id missing")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("Telegram message sent successfully")
        return True
    except Exception as exc:
        logger.warning("Failed to send Telegram message: %s", exc)
        return False
