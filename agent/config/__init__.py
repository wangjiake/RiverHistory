"""Configuration loader."""

import os
import yaml

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "settings.yaml")

def load_config(path: str = None) -> dict:
    path = path or _CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    provider = raw.get("llm_provider", "local")
    llm_config = raw.get(provider, raw.get("local", {}))
    raw["llm"] = llm_config

    db = raw.get("database", {})
    raw["db_name"] = db.get("name", "Riverse")
    raw["db_user"] = db.get("user", "postgres")
    raw["db_host"] = db.get("host", "localhost")

    raw.setdefault("language", "zh")

    return raw
