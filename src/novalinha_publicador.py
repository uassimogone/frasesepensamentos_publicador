import base64
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cairosvg
import requests
from PIL import Image


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


def materialize_asset(asset) -> Path:
    """Baixa, quando necessário, e converte o arquivo final para JPEG aceito pelo Instagram."""
    runtime_dir = Path("runtime_assets")
    runtime_dir.mkdir(exist_ok=True)

    asset_text = str(asset)
    if asset_text.startswith(("https://", "http://")):
        from urllib.parse import urlparse
        remote_name = Path(urlparse(asset_text).path).name or "asset.png"
        downloaded = runtime_dir / remote_name
        response = requests.get(asset_text, timeout=60)
        response.raise_for_status()
        downloaded.write_bytes(response.content)
        asset_path = downloaded
    else:
        asset_path = Path(asset_text)

    suffix = asset_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return asset_path

    target = runtime_dir / f"{asset_path.stem}.jpg"

    if suffix == ".svg":
        svg_text = asset_path.read_text(encoding="utf-8")

        # O slide 1 usa fotografia real externa. Incorporamos os bytes no SVG
        # antes da conversão para tornar a renderização determinística.
        marker = "{{COW_PHOTO_URL}}"
        if marker in svg_text:
            cow_url = (
                "https://commons.wikimedia.org/wiki/Special:Redirect/file/"
                "Cow_on_pasture%2C_Ehrenbach.jpg"
            )
            response = requests.get(cow_url, timeout=60)
            response.raise_for_status()
            encoded = base64.b64encode(response.content).decode("ascii")
            svg_text = svg_text.replace(
                marker,
                f"data:image/jpeg;base64,{encoded}",
            )

        png_bytes = cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            output_width=1080,
            output_height=1350,
        )
        png_path = runtime_dir / f"{asset_path.stem}.png"
        png_path.write_bytes(png_bytes)
        with Image.open(png_path) as image:
            image.convert("RGB").save(target, "JPEG", quality=94, optimize=True)
        return target

    if suffix in {".png", ".webp"}:
        with Image.open(asset_path) as image:
            image.convert("RGB").save(target, "JPEG", quality=94, optimize=True)
        return target

    raise RuntimeError(f"Formato de arquivo não suportado: {asset_path}")


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

    local_assets = [a for a in assets if not str(a).startswith(("https://", "http://"))]
    missing = [str(a) for a in local_assets if not Path(a).exists()]
    if missing:
        raise FileNotFoundError("Arquivos ausentes: " + ", ".join(missing))

    final_paths = [materialize_asset(asset) for asset in assets]
    return tipo, final_paths


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
