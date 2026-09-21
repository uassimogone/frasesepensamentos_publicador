import base64
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


IG_USER_ID = os.environ["INSTAGRAM_USER_ID"]
IG_TOKEN = os.environ["INSTAGRAM_ACCESS_TOKEN"]
IMGBB_KEY = os.environ["IMGBB_API_KEY"]
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v25.0")
GRAPH_API_HOST = os.environ.get("META_GRAPH_API_HOST", "https://graph.facebook.com").rstrip("/")

DB_DIR = Path("database")
DATA_FILE = DB_DIR / "novalinha_posts.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def notify(text):
    if not BOT_TOKEN or not CHAT_ID:
        print(text)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=15,
        ).raise_for_status()
    except requests.RequestException as exc:
        print(f"Falha no aviso Telegram: {exc}")


def upload_to_imgbb(image_path: Path) -> str:
    with image_path.open("rb") as fh:
        payload = base64.b64encode(fh.read()).decode("utf-8")
    r = requests.post("https://api.imgbb.com/1/upload", data={"key": IMGBB_KEY, "image": payload}, timeout=45)
    r.raise_for_status()
    data = r.json()
    url = data.get("data", {}).get("url")
    if not url:
        raise RuntimeError(f"ImgBB não retornou URL para {image_path.name}")
    return url


def graph_post(path, data):
    base = f"{GRAPH_API_HOST}/{GRAPH_API_VERSION}"
    r = requests.post(f"{base}/{path}", params={"access_token": IG_TOKEN}, data=data, timeout=45)
    try:
        payload = r.json()
    except ValueError:
        payload = {"body": r.text[:500]}
    if r.status_code != 200 or not payload.get("id"):
        raise RuntimeError(f"Meta recusou {path}: {payload}")
    return payload["id"]


def wait_container(container_id):
    base = f"{GRAPH_API_HOST}/{GRAPH_API_VERSION}"
    for _ in range(18):
        time.sleep(8)
        r = requests.get(
            f"{base}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
            timeout=30,
        )
        payload = r.json()
        status = payload.get("status_code", "")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Erro de processamento Meta: {payload}")
    raise RuntimeError("Timeout aguardando processamento do carrossel.")


def publish_carousel(image_paths, caption):
    child_ids = []
    for path in image_paths:
        url = upload_to_imgbb(path)
        child_id = graph_post(
            f"{IG_USER_ID}/media",
            {"image_url": url, "is_carousel_item": "true"},
        )
        child_ids.append(child_id)

    parent_id = graph_post(
        f"{IG_USER_ID}/media",
        {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption[:2200],
        },
    )
    wait_container(parent_id)
    return graph_post(f"{IG_USER_ID}/media_publish", {"creation_id": parent_id})


def run():
    if not DATA_FILE.exists():
        print("Fila da nova linha editorial ainda não existe.")
        return

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    post = next(
        (
            p for p in data.get("posts", [])
            if p.get("aprovado") is True and not p.get("publicado")
        ),
        None,
    )
    if not post:
        print("Nenhum carrossel aprovado pendente.")
        return

    paths = [DB_DIR / name for name in post.get("imagens", [])]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError("Arquivos ausentes: " + ", ".join(missing))
    if len(paths) < 2:
        raise RuntimeError("Carrossel precisa de pelo menos 2 imagens.")

    try:
        media_id = publish_carousel(paths, post.get("caption", ""))
        post["publicado"] = True
        post["instagram_media_id"] = media_id
        post["publicado_em"] = datetime.now(TIMEZONE).isoformat()
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        notify(f"✅ Carrossel {post.get('id')} publicado no Instagram.")
    except Exception as exc:
        traceback.print_exc()
        notify(f"❌ Erro ao publicar carrossel {post.get('id')}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    run()
