import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaPhoto


API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
STRING_SESSION = os.environ["TELEGRAM_STRING_SESSION"]
CONTENT_CHAT_ID = int(os.environ["TELEGRAM_CONTENT_CHAT_ID"])

DB_DIR = Path("database")
DB_DIR.mkdir(exist_ok=True)
DATA_FILE = DB_DIR / "novalinha_posts.json"
STATE_FILE = DB_DIR / "novalinha_estado.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def load_data():
    if not DATA_FILE.exists():
        return {"posts": []}
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"posts": []}


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_today(message):
    dt = message.date
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TIMEZONE).date() == datetime.now(TIMEZONE).date()


async def main():
    data = load_data()
    known = {str(p.get("telegram_grouped_id") or p.get("telegram_message_id")) for p in data.get("posts", [])}
    state = load_state()

    async with TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH) as client:
        await client.get_dialogs()
        chat = await client.get_entity(CONTENT_CHAT_ID)
        messages = [m async for m in client.iter_messages(chat, limit=120)]
        messages = [m for m in messages if is_today(m)]
        messages.sort(key=lambda m: m.id)

        groups = {}
        for m in messages:
            if not isinstance(m.media, MessageMediaPhoto):
                continue
            key = str(m.grouped_id or m.id)
            groups.setdefault(key, []).append(m)

        candidates = []
        for key, items in groups.items():
            if key in known:
                continue
            combined = "\n".join((m.message or "") for m in items)
            if "CARROSSEL PRONTO" in combined:
                candidates.append((max(m.id for m in items), key, items))

        if not candidates:
            print("Nenhum carrossel novo encontrado.")
            return

        collected = 0
        for _, key, items in sorted(candidates):
            items.sort(key=lambda m: m.id)
            first_caption = next((m.message for m in items if m.message), "")
            pauta_id = first_caption.split("—", 1)[0].strip() if "—" in first_caption else f"telegram-{items[0].id}"

            image_names = []
            for idx, msg in enumerate(items, start=1):
                name = f"novalinha_{pauta_id}_{idx:02d}.jpg".replace("/", "-")
                path = DB_DIR / name
                await client.download_media(msg, file=str(path))
                image_names.append(name)

            last_album_id = max(m.id for m in items)
            next_album_first_id = min(
                [min(m.id for m in other_items) for _, other_key, other_items in candidates if min(m.id for m in other_items) > last_album_id],
                default=10**18,
            )
            caption = ""
            for m in messages:
                if last_album_id < m.id < next_album_first_id and not m.media and (m.message or "").startswith("Legenda:"):
                    caption = (m.message or "")[len("Legenda:"):].strip()
                    break

            data.setdefault("posts", []).append({
                "id": pauta_id,
                "imagens": image_names,
                "caption": caption,
                "telegram_grouped_id": key,
                "telegram_message_id": items[0].id,
                "coletado_em": datetime.now(TIMEZONE).isoformat(),
                "aprovado": False,
                "publicado": False,
            })
            known.add(key)
            state["ultimo_grouped_id"] = key
            collected += 1

        save_data(data)
        state["atualizado_em"] = datetime.now(TIMEZONE).isoformat()
        save_state(state)
        print(f"{collected} carrossel(is) coletado(s). Aguardando aprovação.")


if __name__ == "__main__":
    asyncio.run(main())
