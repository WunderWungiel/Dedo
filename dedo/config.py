import yaml
import os
from urllib.parse import quote_plus, urlsplit

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# DEDO_CONFIG overrides the default of config.yaml at the repo root.
path = os.environ.get("DEDO_CONFIG") or os.path.join(ROOT_DIR, "config.yaml")

class ConfigError(ValueError):
    pass


try:
    with open(path, "r") as f:
        config = yaml.safe_load(f.read())
except FileNotFoundError as error:
    raise ConfigError(
        f"Configuration file not found at {path!r}. "
        "To get started, copy config.yaml.example to config.yaml at the repo root "
        "or set DEDO_CONFIG to an existing configuration file."
    ) from error


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_str(value):
    return isinstance(value, str)


def _is_port(value):
    # Compose passes strings; the driver also accepts an unquoted integer. Only
    # ASCII decimal digits are a port, so Unicode digits such as '²' are not.
    if _is_int(value):
        return 1 <= value <= 65535
    if not isinstance(value, str):
        return False
    digits = value.strip()
    return (digits.isascii() and digits.isdecimal() and len(digits) <= 5
            and 1 <= int(digits) <= 65535)


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
    port = (MONGO.get('port') or '').strip()
    if port and not _is_port(port):
        problems.append(
            f"{MONGO_ENV['port']} must be an ASCII decimal port in the range "
            f"1-65535, got {port!r}")
    if bool(MONGO.get('user')) != bool(MONGO.get('password')):
        problems.append(f"set both {MONGO_ENV['user']} and {MONGO_ENV['password']}, or neither")
    return problems


def _is_public_url(value):
    if not _is_str(value) or not value.strip():
        return False
    try:
        url = urlsplit(value.strip())
        url.port  # raises ValueError for a malformed port
    except ValueError:
        return False
    return (url.scheme in ('http', 'https') and bool(url.hostname)
            and url.username is None and url.password is None
            and not url.query and not url.fragment)


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

    if 'mongodb_uri' in data:
        problems.append(
            "mongodb_uri is no longer supported; remove it and set MONGO_DB; "
            "MONGO_HOST, MONGO_PORT, MONGO_USER and MONGO_PASSWORD are optional"
        )

    content_dir = data.get('content_dir')
    if content_dir is not None and not (_is_str(content_dir) and content_dir.strip()):
        problems.append(f"content_dir must be a non-empty string, got {content_dir!r}")

    canonical_url = data.get('canonical_url')
    if canonical_url is not None and not _is_public_url(canonical_url):
        problems.append(
            "canonical_url must be an absolute HTTP(S) URL without credentials, "
            "query or fragment")

    verification = data.get('google_site_verification')
    if verification is not None and not (_is_str(verification) and verification.strip()):
        problems.append(
            f"google_site_verification must be a non-empty string, got {verification!r}")

    problems += _mongo_problems()

    if problems:
        raise ConfigError(
            f"Invalid configuration in {path} or the environment (see config.yaml.example and .env.example):\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


_validate(config)


CONTENT_DIR = os.path.normpath(
    os.path.join(ROOT_DIR, config.get('content_dir') or 'content'))

# Where search engines should index the site: canonical links, og:url and the sitemap.
# Optional. None means use the scheme and host of the request itself.
_canonical_url = config.get('canonical_url')
if _canonical_url is None:
    CANONICAL_URL = None
else:
    _split = urlsplit(_canonical_url.strip())
    CANONICAL_URL = _split._replace(path=_split.path.rstrip('/'))


MONGO_DB = MONGO['db']
MONGO_HOST = MONGO.get('host') or 'localhost'
MONGO_PORT = (MONGO.get('port') or '').strip() or '27017'
MONGO_USER = MONGO.get('user') or ''
MONGO_PASSWORD = MONGO.get('password') or ''

if MONGO_USER:
    MONGO_URI = (
        f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASSWORD)}"
        f"@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}?authSource=admin"
    )
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"
