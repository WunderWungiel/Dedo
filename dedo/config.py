import os
from urllib.parse import quote_plus

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.environ.get("DEDO_CONFIG") or os.path.join(ROOT_DIR, "config.yaml")


class ConfigError(ValueError):
    pass


REQUIRED_KEYS = {
    "allow_indexing": "must be true or false",
    "per_page": "must be a positive integer",
    "api_prefix": "must be a non-empty string starting with '/'",
}

_MISSING = object()


def _lookup(data, dotted_key):
    value = data
    for part in dotted_key.split("."):
        if not isinstance(value, dict) or part not in value:
            return _MISSING
        value = value[part]
    return value


def _validate(data):
    if not isinstance(data, dict):
        raise ConfigError(
            f"Invalid configuration in {path}: expected a mapping.\n"
            "See config.yaml.example for a working example."
        )

    problems = []

    for key, message in REQUIRED_KEYS.items():
        value = _lookup(data, key)

        if value is _MISSING:
            problems.append(f"{key} is missing")
        elif key == "allow_indexing" and not isinstance(value, bool):
            problems.append(f"{key} {message}")
        elif key == "per_page" and (
            isinstance(value, bool) or not isinstance(value, int) or value <= 0
        ):
            problems.append(f"{key} {message}")
        elif key == "api_prefix" and (
            not isinstance(value, str) or not value or not value.startswith("/")
        ):
            problems.append(f"{key} {message}")

    content_dir = _lookup(data, "content_dir")
    if content_dir is not _MISSING and (
        not isinstance(content_dir, str) or not content_dir.strip()
    ):
        problems.append("content_dir must be a non-empty string")

    if problems:
        details = "\n".join(f"  - {problem}" for problem in problems)
        raise ConfigError(
            f"Invalid configuration in {path}:\n{details}\n"
            "See config.yaml.example for a working example."
        )


try:
    with open(path, "r") as f:
        config = yaml.safe_load(f.read())
except FileNotFoundError as error:
    raise ConfigError(
        f"Configuration file not found: {path}\n"
        "copy config.yaml.example to config.yaml, or set DEDO_CONFIG to its path."
    ) from error

_validate(config)


MONGO_DB = (os.environ.get("MONGO_DB") or "").strip()
if not MONGO_DB:
    raise ConfigError("MONGO_DB must be set to a non-empty database name")

MONGO_HOST = os.environ.get("MONGO_HOST") or "localhost"
MONGO_PORT = os.environ.get("MONGO_PORT") or "27017"
if not MONGO_PORT.isdigit():
    raise ConfigError(f"MONGO_PORT must be digits, got {MONGO_PORT!r}")

MONGO_USER = os.environ.get("MONGO_USER") or ""
MONGO_PASSWORD = os.environ.get("MONGO_PASSWORD") or ""
if bool(MONGO_USER) != bool(MONGO_PASSWORD):
    raise ConfigError("MONGO_USER and MONGO_PASSWORD must be set together")

if MONGO_USER:
    MONGO_URI = (
        f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}"
        f"@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}?authSource=admin"
    )
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
