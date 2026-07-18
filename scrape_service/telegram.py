"""
scrape_service/telegram.py
────────────────────────────
Sends Telegram messages via the Bot API.

Setup:
  1. Create a bot with @BotFather → copy the token.
  2. Get your chat ID:
       - For personal messages: message @userinfobot
       - For a group: add the bot to the group, then call
         https://api.telegram.org/bot<TOKEN>/getUpdates
  3. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in settings.py or .env
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message to the configured Telegram chat.
    Returns True on success, False on failure.
    """
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.warning("Telegram bot token not configured — skipping notification.")
        return False
    if not chat_id or chat_id == "YOUR_CHAT_ID_HERE":
        logger.warning("Telegram chat ID not configured — skipping notification.")
        return False

    url = TELEGRAM_API.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    logger.info("POST %s chat_id=%s", url, chat_id)
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info("Telegram notification sent (status=%s).", resp.status_code)
        return True
    except requests.RequestException as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


def build_job_message(job, matched_keywords: list[str]) -> str:
    """Build a nicely formatted Telegram HTML message for a matched job."""
    kw_tags = " ".join(f"<code>{kw}</code>" for kw in matched_keywords)

    lines = [
        "🔔 <b>New LinkedIn Job Match!</b>",
        "",
        f"💼 <b>{_esc(job.title)}</b>",
        f"🏢 {_esc(job.company)}",
    ]

    if job.location:
        lines.append(f"📍 {_esc(job.location)}")
    if job.employment_type:
        lines.append(f"🕐 {_esc(job.employment_type)}")
    if job.seniority_level:
        lines.append(f"📊 {_esc(job.seniority_level)}")
    if job.posted_date:
        lines.append(f"📅 {_esc(job.posted_date)}")
    if job.poster_name:
        if job.poster_profile_url:
            lines.append(
                f'🙋 Posted by <a href="{job.poster_profile_url}">{_esc(job.poster_name)}</a>'
            )
        else:
            lines.append(f"🙋 Posted by {_esc(job.poster_name)}")

    lines += [
        "",
        f"🔑 Matched keywords: {kw_tags}",
        "",
        f"🔗 {job.url}",
        # f'🔗 <a href="{job.url}">View on LinkedIn</a>',
    ]

    return "\n".join(lines)


def _esc(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
