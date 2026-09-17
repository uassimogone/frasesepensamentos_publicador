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
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v25.0")
GRAPH_API_HOST = os.environ.get(
    "META_GRAPH_API_HOST", "https://graph.facebook.com"
).rstrip("/")

DB_DIR = Path("database")
DATA_FILE = DB_DIR / "posts_do_dia.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def notify_telegram(text: str) -> None:
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"Erro ao avisar Telegram: {exc}")


def upload_to_imgbb(image_path: Path) -> str:
    print(f" -> [Etapa 1] Hospedando imagem no ImgBB: {image_path}")
    with image_path.open("rb") as image_file:
        image_b64 = base64.b64encode(image_file.read()).decode("utf-8")

    response = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_KEY, "image": image_b64},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"ImgBB HTTP {response.status_code}: {response.text[:300]}"
        )

    try:
        image_url = response.json()["data"]["url"]
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"ImgBB não retornou uma URL válida: {response.text[:300]}"
        ) from exc

    print(" -> [Etapa 1 OK] URL pública criada.")
    return image_url


def publish_story(image_url: str) -> str:
    print(" -> [Etapa 2] Criando contêiner de Story na Meta...")
    base_url = f"{GRAPH_API_HOST}/{GRAPH_API_VERSION}"
    container_id = None
    last_response = {}

    for attempt in range(1, 4):
        response = requests.post(
            f"{base_url}/{IG_USER_ID}/media",
            params={"access_token": IG_TOKEN},
            data={"image_url": image_url, "media_type": "STORIES"},
            timeout=30,
        )
        try:
            last_response = response.json()
        except ValueError:
            last_response = {"http_status": response.status_code, "body": response.text[:300]}

        container_id = last_response.get("id")
        if container_id:
            break

        print(f" -> Tentativa {attempt}/3 recusada pela Meta: {last_response}")
        if attempt < 3:
            time.sleep(10)

    if not container_id:
        raise RuntimeError(f"Meta negou a criação do Story: {last_response}")

    print(f" -> Contêiner {container_id} criado. Aguardando processamento...")
    for _ in range(12):
        time.sleep(10)
        status_response = requests.get(
            f"{base_url}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": IG_TOKEN,
            },
            timeout=20,
        ).json()
        status = status_response.get("status_code", "")
        print(f"     ... Status da Meta: {status}")
        if status == "FINISHED":
            break
        if status in {"ERROR", "EXPIRED"}:
            raise RuntimeError(
                f"Erro no processamento do Story pela Meta: {status_response}"
            )
    else:
        raise RuntimeError("A Meta demorou mais de dois minutos para processar o Story.")

    print(" -> [Etapa 3] Publicando o Story...")
    publish_response = requests.post(
        f"{base_url}/{IG_USER_ID}/media_publish",
        params={"access_token": IG_TOKEN},
        data={"creation_id": container_id},
        timeout=30,
    )
    try:
        publish_payload = publish_response.json()
    except ValueError:
        publish_payload = {}

    media_id = publish_payload.get("id")
    if publish_response.status_code != 200 or not media_id:
        raise RuntimeError(
            f"Erro na publicação final do Story: {publish_response.text[:300]}"
        )

    print(" -> [Etapa 3 OK] Story publicado!")
    return media_id


def run_queue() -> None:
    if not DATA_FILE.exists():
        print("Fila não encontrada. Execute o coletor primeiro.")
        sys.exit(1)

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    story = next(
        (item for item in data.get("posts", []) if not item.get("publicado")),
        None,
    )
    if not story:
        print("Não há Story pendente para publicar.")
        return

    image_path = DB_DIR / story["imagem"]
    if not image_path.exists():
        message = f"Arquivo de imagem '{story['imagem']}' não foi encontrado."
        notify_telegram(f"❌ Erro estrutural no Story: {message}")
        raise FileNotFoundError(message)

    try:
        public_url = upload_to_imgbb(image_path)
        media_id = publish_story(public_url)
        story["publicado"] = True
        story["instagram_media_id"] = media_id
        story["publicado_em"] = datetime.now(TIMEZONE).isoformat()
        DATA_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        notify_telegram("✅ Story diário publicado com sucesso no Instagram.")
    except Exception as exc:
        print("\n" + "=" * 50)
        traceback.print_exc()
        print("=" * 50 + "\n")
        notify_telegram(f"❌ Erro ao publicar o Story:\n{exc}")
        sys.exit(1)


if __name__ == "__main__":
    run_queue()
