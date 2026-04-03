"""Label database and data path resolution."""
import json
import os
from pathlib import Path


def get_data_dir() -> Path:
    """Return the data directory for label_db.json and .ble_cache.json.

    Checks NIIMBOT_DATA_DIR env var first, otherwise uses <project_root>/data/.
    """
    env = os.environ.get("NIIMBOT_DATA_DIR")
    if env:
        return Path(env)
    # Default: <project_root>/data/ (3 levels up from src/niimbot/labels.py)
    return Path(__file__).parents[2] / "data"


def get_label_db_path() -> Path:
    return get_data_dir() / "label_db.json"


def get_ble_cache_path() -> Path:
    return get_data_dir() / ".ble_cache.json"


def load_label_db() -> dict:
    path = get_label_db_path()
    if path.exists():
        return json.loads(path.read_text())
    return {"labels": {}}


def save_label_db(db: dict) -> None:
    path = get_label_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(db, indent=2) + "\n")
