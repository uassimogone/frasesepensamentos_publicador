import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


CREATOR_REPO = "uassimogone/criativo_novalinhaeditorial_criacao"
BRANCH = "main"
API_BASE = f"https://api.github.com/repos/{CREATOR_REPO}/contents"
RAW_BASE = f"https://raw.githubusercontent.com/{CREATOR_REPO}/{BRANCH}"

DB_DIR = Path("database")
DB_DIR.mkdir(exist_ok=True)
DATA_FILE = DB_DIR / "novalinha_posts.json"
STATE_FILE = DB_DIR / "novalinha_estado.json"
TIMEZONE = ZoneInfo("America/Sao_Paulo")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api_list(path):
    r = requests.get(
        f"{API_BASE}/{path}",
        params={"ref": BRANCH},
        headers={"User-Agent": "UassiNovaLinhaPublisher/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_json_raw(path):
    r = requests.get(f"{RAW_BASE}/{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def download_raw(path, target):
    r = requests.get(f"{RAW_BASE}/{path}", timeout=45)
    r.raise_for_status()
    target.write_bytes(r.content)


def main():
    data = load_json(DATA_FILE, {"posts": []})
    state = load_json(STATE_FILE, {})
    known = {
        f"{p.get('id')}::v{p.get('visual_revision', 1)}"
        for p in data.get("posts", [])
    }

    dates = [
        item["name"]
        for item in api_list("output")
        if item.get("type") == "dir"
    ]
    dates = sorted(dates, reverse=True)[:7]

    collected = 0
    for date_dir in sorted(dates):
        packages = [
            item for item in api_list(f"output/{date_dir}")
            if item.get("type") == "dir"
        ]
        for pkg in packages:
            manifest_path = f"output/{date_dir}/{pkg['name']}/manifest.json"
            try:
                manifest = fetch_json_raw(manifest_path)
            except requests.RequestException:
                continue

            if manifest.get("formato") != "CARROSSEL":
                continue
            if manifest.get("status") != "READY_TO_PUBLISH":
                continue

            revision = int(manifest.get("visual_revision", 1))
            key = f"{manifest.get('id')}::v{revision}"
            if key in known:
                continue

            image_names = []
            for idx, asset in enumerate(manifest.get("assets", []), start=1):
                if not str(asset).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                remote_path = f"output/{date_dir}/{pkg['name']}/{asset}"
                local_name = f"novalinha_{manifest['id']}_v{revision}_{idx:02d}{Path(asset).suffix}"
                local_path = DB_DIR / local_name
                download_raw(remote_path, local_path)
                image_names.append(local_name)

            if len(image_names) < 2:
                continue

            data.setdefault("posts", []).append({
                "id": manifest["id"],
                "visual_revision": revision,
                "visual_family": manifest.get("visual_family", ""),
                "imagens": image_names,
                "caption": manifest.get("caption", ""),
                "creator_manifest": manifest_path,
                "coletado_em": datetime.now(TIMEZONE).isoformat(),
                "aprovado": False,
                "publicado": False,
            })
            known.add(key)
            collected += 1

    state["ultima_coleta_em"] = datetime.now(TIMEZONE).isoformat()
    state["novos_na_ultima_coleta"] = collected
    save_json(DATA_FILE, data)
    save_json(STATE_FILE, state)
    print(f"{collected} carrossel(is) novo(s) coletado(s) do repositório de criação.")


if __name__ == "__main__":
    main()
