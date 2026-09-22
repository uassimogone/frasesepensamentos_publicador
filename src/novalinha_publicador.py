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

DATA_FILE = Path("database/novalinha_posts.json")
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
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_KEY, "image": payload},
        timeout=45,
    )
    r.raise_for_status()
    data = r.json()
    url = data.get("data", {}).get("url")
    if not url:
        raise RuntimeError(f"ImgBB não retornou URL para {image_path}")
    return url


def graph_post(path, data):
    base = f"{GRAPH_API_HOST}/{GRAPH_API_VERSION}"
    r = requests.post(
        f"{base}/{path}",
        params={"access_token": IG_TOKEN},
        data=data,
        timeout=45,
    )
    try:
        payload = r.json()
    except ValueError:
        payload = {"body": r.text[:500]}
    if r.status_code != 200 or not payload.get("id"):
        raise RuntimeError(f"Meta recusou {path}: {payload}")
    return payload["id"]


def wait_container(container_id):
    base = f"{GRAPH_API_HOST}/{GRAPH_API_VERSION}"
    for _ in range(20):
        time.sleep(6)
        r = requests.get(
            f"{base}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        status = payload.get("status_code", "")
        if status == "FINISHED":
            return
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Erro de processamento Meta: {payload}")
    raise RuntimeError("Timeout aguardando processamento do conteúdo.")


def publish_static(image_path, caption):
    url = upload_to_imgbb(image_path)
    container_id = graph_post(
        f"{IG_USER_ID}/media",
        {"image_url": url, "caption": caption[:2200]},
    )
    wait_container(container_id)
    return graph_post(f"{IG_USER_ID}/media_publish", {"creation_id": container_id})


def publish_carousel(image_paths, caption):
    child_ids = []
    for path in image_paths:
        url = upload_to_imgbb(path)
        child_id = graph_post(
            f"{IG_USER_ID}/media",
            {"image_url": url, "is_carousel_item": "true"},
        )
        wait_container(child_id)
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


def already_published_today(posts):
    today = datetime.now(TIMEZONE).date()
    for post in posts:
        published_at = post.get("publicado_em")
        if not published_at:
            continue
        try:
            if datetime.fromisoformat(published_at).astimezone(TIMEZONE).date() == today:
                return True
        except ValueError:
            continue
    return False


def validate_post(post):
    status = post.get("status")
    if status != "QUEUED":
        raise RuntimeError(f"Item {post.get('id')} não está em status QUEUED.")

    scheduled_for = post.get("scheduled_for")
    if not scheduled_for:
        raise RuntimeError(f"Item {post.get('id')} não possui scheduled_for.")

    tipo = str(post.get("tipo", "")).upper()
    if tipo not in {"CARROSSEL", "ESTATICO"}:
        raise RuntimeError(f"Tipo inválido em {post.get('id')}: {tipo}")

    assets = post.get("assets") or []
    if tipo == "ESTATICO" and len(assets) != 1:
        raise RuntimeError("Post estático deve possuir exatamente 1 arquivo.")
    if tipo == "CARROSSEL" and not 2 <= len(assets) <= 7:
        raise RuntimeError("Carrossel deve possuir entre 2 e 7 arquivos.")

    paths = [Path(asset) for asset in assets]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Arquivos ausentes: " + ", ".join(missing))

    return tipo, paths


def run():
    if not DATA_FILE.exists():
        print("Fila da nova linha editorial ainda não existe.")
        return

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    posts = data.get("posts", [])

    if already_published_today(posts):
        print("Já houve uma publicação da nova linha editorial hoje. Limite diário preservado.")
        return

    now = datetime.now(TIMEZONE)

    def scheduled_time(post):
        raw = post.get("scheduled_for")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TIMEZONE)
            return dt.astimezone(TIMEZONE)
        except ValueError:
            return None

    due = []
    for candidate in posts:
        if candidate.get("status") != "QUEUED":
            continue
        when = scheduled_time(candidate)
        if when is None:
            continue
        if when <= now:
            due.append((when, candidate))

    due.sort(key=lambda item: item[0])
    post = due[0][1] if due else None

    if not post:
        print("Nenhum conteúdo com data de publicação vencida ou prevista para este horário.")
        return

    try:
        tipo, paths = validate_post(post)
        post["tentativa_em"] = datetime.now(TIMEZONE).isoformat()

        if tipo == "ESTATICO":
            media_id = publish_static(paths[0], post.get("caption", ""))
        else:
            media_id = publish_carousel(paths, post.get("caption", ""))

        post["status"] = "PUBLISHED"
        post["publicado"] = True
        post["instagram_media_id"] = media_id
        post["publicado_em"] = datetime.now(TIMEZONE).isoformat()
        post.pop("erro", None)

        DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        notify(f"Conteúdo {post.get('id')} publicado no Instagram.")
    except Exception as exc:
        traceback.print_exc()
        post["status"] = "ERROR"
        post["erro"] = str(exc)
        post["erro_em"] = datetime.now(TIMEZONE).isoformat()
        DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        notify(f"Erro ao publicar {post.get('id')}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    run()
