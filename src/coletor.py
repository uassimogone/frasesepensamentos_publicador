import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto


API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION = os.environ["TELEGRAM_STRING_SESSION"]

SOURCE_BOT_TOKEN = os.environ.get("TELEGRAM_SOURCE_BOT_TOKEN", "").strip()
CONTENT_CHAT_ID = os.environ.get("TELEGRAM_CONTENT_CHAT_ID", "").strip()
ALERT_BOT_TOKEN = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN", SOURCE_BOT_TOKEN).strip()
ALERT_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

DB_DIR = Path("database")
DB_DIR.mkdir(exist_ok=True)
DATA_FILE = DB_DIR / "posts_do_dia.json"
STATE_FILE = DB_DIR / "estado_coletor.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def resolve_content_chat_id() -> int:
    if CONTENT_CHAT_ID:
        return int(CONTENT_CHAT_ID)
    if SOURCE_BOT_TOKEN and ":" in SOURCE_BOT_TOKEN:
        return int(SOURCE_BOT_TOKEN.split(":", 1)[0])
    raise ValueError(
        "Configure TELEGRAM_CONTENT_CHAT_ID ou TELEGRAM_SOURCE_BOT_TOKEN."
    )


def notify_telegram(text: str) -> None:
    if not (ALERT_BOT_TOKEN and ALERT_CHAT_ID):
        print(f"[aviso não enviado] {text}")
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage",
            json={"chat_id": ALERT_CHAT_ID, "text": text},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Erro ao avisar Telegram: {exc}")


def load_last_message_id() -> int | None:
    if not STATE_FILE.exists():
        return None
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        value = payload.get("ultimo_message_id")
        return int(value) if value is not None else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def save_last_message_id(message_id: int) -> None:
    STATE_FILE.write_text(
        json.dumps({"ultimo_message_id": message_id}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )


def pending_count() -> int:
    if not DATA_FILE.exists():
        return 0
    try:
        payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return sum(1 for item in payload.get("posts", []) if not item.get("publicado"))
    except (OSError, json.JSONDecodeError):
        return 0


def is_from_today(message) -> bool:
    message_date = message.date
    if message_date.tzinfo is None:
        message_date = message_date.replace(tzinfo=timezone.utc)
    return message_date.astimezone(TIMEZONE).date() == datetime.now(TIMEZONE).date()


async def collect_story() -> None:
    content_chat_id = resolve_content_chat_id()
    print(f"Iniciando coleta do Story no Telegram (chat: {content_chat_id})...")

    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()
        chat = await client.get_entity(content_chat_id)

        messages = [message async for message in client.iter_messages(chat, limit=50)]
        messages.reverse()

        last_processed = load_last_message_id()
        newest_seen = max((message.id for message in messages), default=(last_processed or 0))

        if last_processed is None:
            new_messages = [message for message in messages if is_from_today(message)]
        else:
            new_messages = [message for message in messages if message.id > last_processed]

        photos = [
            message
            for message in new_messages
            if isinstance(message.media, MessageMediaPhoto)
        ]

        if not photos:
            save_last_message_id(newest_seen)
            print("Nenhuma arte nova encontrada. A fila atual foi preservada.")
            return

        selected = photos[-1]
        image_name = "story_01.png"
        image_path = DB_DIR / image_name

        if pending_count():
            notify_telegram(
                "⚠️ A arte pendente anterior foi substituída por uma nova arte."
            )

        print(f"Baixando a arte da mensagem {selected.id}...")
        await client.download_media(selected, file=str(image_path))

        queue = {
            "posts": [
                {
                    "id": 1,
                    "imagem": image_name,
                    "publicado": False,
                    "telegram_message_id": selected.id,
                    "coletado_em": datetime.now(TIMEZONE).isoformat(),
                }
            ]
        }
        DATA_FILE.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        save_last_message_id(newest_seen)
        print("Coleta finalizada. Uma arte foi preparada para publicação.")


if __name__ == "__main__":
    asyncio.run(collect_story())
