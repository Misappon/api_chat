"""Application configuration stored outside the project directory."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

APP_DIR_NAME = "APIChat"
DEFAULT_DATABASE: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "",
    "name": "api_chat",
}
DEFAULT_CONFIG: dict[str, Any] = {
    "database": DEFAULT_DATABASE,
    "last_provider_id": None,
    "last_conversation_id": None,
    "font_scale": 1.0,
    "attachment_image_mb": 10,
    "attachment_text_mb": 2,
    "attachment_pdf_mb": 20,
    "search_sources": [
        {
            "id": "bing",
            "type": "bing",
            "label": "Bing",
            "endpoint": "https://cn.bing.com/search",
            "enabled": True,
            "api_key": "",
        }
    ],
    "window": {"width": 1320, "height": 860, "x": None, "y": None},
}


def app_data_dir() -> Path:
    """Return the per-user data directory, allowing an override for tests."""
    override = os.environ.get("APICHAT_HOME")
    if override:
        path = Path(override).expanduser()
    else:
        base = os.environ.get("APPDATA") or str(Path.home())
        path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    override = os.environ.get("APICHAT_CONFIG")
    return Path(override).expanduser() if override else app_data_dir() / "config.json"


class Config:
    """Small JSON-backed configuration object with atomic saves."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()
        self.data: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            # A corrupt config should never prevent the app from starting.
            return
        if not isinstance(raw, dict):
            return
        for key, value in raw.items():
            if key == "database" and isinstance(value, dict):
                merged = copy.deepcopy(DEFAULT_DATABASE)
                merged.update({k: v for k, v in value.items() if k in DEFAULT_DATABASE})
                self.data["database"] = merged
            elif key == "window" and isinstance(value, dict):
                merged = copy.deepcopy(DEFAULT_CONFIG["window"])
                merged.update(value)
                self.data["window"] = merged
            else:
                self.data[key] = value

    @property
    def database(self) -> dict[str, Any]:
        env_name = os.environ.get("APICHAT_DB_NAME")
        if env_name:
            db = copy.deepcopy(self.data["database"])
            db["name"] = env_name
            return db
        return copy.deepcopy(self.data["database"])

    @database.setter
    def database(self, value: dict[str, Any]) -> None:
        self.data["database"] = {
            "host": str(value.get("host", "127.0.0.1")),
            "port": int(value.get("port", 3306)),
            "user": str(value.get("user", "root")),
            "password": str(value.get("password", "")),
            "name": str(value.get("name", "api_chat")),
        }

    @property
    def window(self) -> dict[str, Any]:
        return self.data.setdefault("window", copy.deepcopy(DEFAULT_CONFIG["window"]))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(
            prefix=".config-", suffix=".json", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
