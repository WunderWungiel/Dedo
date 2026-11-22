import yaml
import os
from urllib.parse import quote_plus

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# DEDO_CONFIG overrides the default of config.yaml at the repo root.
path = os.environ.get("DEDO_CONFIG") or os.path.join(ROOT_DIR, "config.yaml")

with open(path, "r") as f:
    config = yaml.safe_load(f.read())

class ConfigError(ValueError):
    pass


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value):
    return isinstance(value, str)


def _is_port(value):
    # The MongoDB driver also accepts a quoted port.
    return _is_int(value) or (isinstance(value, str) and value.strip().isdigit())


# Every key the app reads, with a check for the value and what the check expects.
REQUIRED_KEYS = {
    'allow_indexing': (lambda value: isinstance(value, bool), "true or false"),
    'per_page': (lambda value: _is_int(value) and value > 0, "a positive integer"),
    'api_prefix': (lambda value: _is_str(value) and value.startswith('/'),
                   "a non-empty string starting with '/'"),
}

# The database connection comes only from these, which Docker compose sets from .env, the
# same values the db container is created with.
MONGO_ENV = {
    'host': 'MONGO_HOST',
    'port': 'MONGO_PORT',
    'db': 'MONGO_DB',
    'user': 'MONGO_USER',
    'password': 'MONGO_PASSWORD',
}
REQUIRED_MONGO_ENV = ('db',)

MONGO = {key: os.environ[var] for key, var in MONGO_ENV.items() if var in os.environ}


def _mongo_problems():
    problems = []
    for key in REQUIRED_MONGO_ENV:
        if not MONGO.get(key):
            problems.append(f"set the {MONGO_ENV[key]} environment variable")
    port = MONGO.get('port')
    if port and not _is_port(port):
        problems.append(f"{MONGO_ENV['port']} must be a port number, got {port!r}")
    if bool(MONGO.get('user')) != bool(MONGO.get('password')):
        problems.append(f"set both {MONGO_ENV['user']} and {MONGO_ENV['password']}, or neither")
    return problems


_MISSING = object()


def _lookup(data, key):
    for part in key.split('.'):
        if not isinstance(data, dict) or part not in data:
            return _MISSING
        data = data[part]
    return data


def _validate(data):
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping; see config.yaml.example")

    problems = []
    for key, (check, expected) in REQUIRED_KEYS.items():
        value = _lookup(data, key)
        if value is _MISSING:
            problems.append(f"{key} is missing")
        elif not check(value):
            problems.append(f"{key} must be {expected}, got {value!r}")

    content_dir = data.get('content_dir')
    if content_dir is not None and not (_is_str(content_dir) and content_dir.strip()):
        problems.append(f"content_dir must be a non-empty string, got {content_dir!r}")

    problems += _mongo_problems()

    if problems:
        raise ConfigError(
            f"Invalid configuration in {path} or the environment (see config.yaml.example and .env.example):\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


_validate(config)


MONGO_DB = MONGO['db']
MONGO_HOST = MONGO.get('host') or 'localhost'
MONGO_PORT = MONGO.get('port') or '27017'
MONGO_USER = MONGO.get('user') or ''
MONGO_PASSWORD = MONGO.get('password') or ''

if MONGO_USER:
    MONGO_URI = (
        f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}"
        f"@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}?authSource=admin"
    )
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
