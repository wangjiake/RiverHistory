"""Configuration loader."""

import logging
import os
import shutil
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "settings.yaml")
_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "settings.yaml.default")

def load_config(path: str = None) -> dict:
    path = path or _CONFIG_PATH
    if not os.path.exists(path) and os.path.exists(_DEFAULT_PATH):
        shutil.copy2(_DEFAULT_PATH, path)
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    provider = raw.get("llm_provider", "local")
    llm_config = raw.get(provider, raw.get("local", {}))
    raw["llm"] = llm_config

    db = raw.get("database", {})
    raw["db_name"] = db.get("name", "Riverse")
    raw["db_user"] = db.get("user", "postgres")
    raw["db_host"] = db.get("host", "localhost")

    raw.setdefault("language", "en")

    _validate_config(raw)

    return raw


def _validate_config(raw: dict):
    db = raw.get("database", {})
    if not db.get("name"):
        raise ValueError("database.name must not be empty")
    if not db.get("user"):
        raise ValueError("database.user must not be empty")

    lang = raw.get("language", "")
    if lang not in ("zh", "en", "ja"):
        logger.warning("Unsupported language '%s', defaulting to 'en'", lang)
        raw["language"] = "en"

    provider = raw.get("llm_provider", "")
    if provider and provider not in ("openai", "local"):
        logger.warning("Unknown llm_provider '%s'", provider)

    llm = raw.get("llm", {})
    temp = llm.get("temperature")
    if temp is not None and not (0 <= temp <= 2):
        logger.warning("temperature %.2f outside [0, 2]", temp)

    max_tokens = llm.get("max_tokens")
    if max_tokens is not None and max_tokens <= 0:
        logger.warning("max_tokens %d is not positive", max_tokens)
