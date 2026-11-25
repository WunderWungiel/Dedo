#!/usr/bin/env python3
"""Request every route once and check the responses.

Run it against a throwaway database:

    MONGO_DB=dedo_test python -m tests.smoke_test

The script fills the empty games collection with a small set of fixtures and
writes the files they reference under the content directory, requests each web
page and the frozen JSON API through the Flask test client, then deletes the
fixture documents and files it created. It refuses to run if the games
collection already holds documents or a fixture file already exists.

Run it from the repo root. DEDO_CONFIG can name a config file other than the
repo root's config.yaml.

Exit status is 0 when every check passes and 1 otherwise.
"""

import os
import subprocess
import sys
import tempfile
import traceback
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from unittest.mock import patch
from xml.etree import ElementTree as ET

from bson import ObjectId
from pymongo.errors import PyMongoError

from dedo import cache, db, helpers
from dedo.app import app
from dedo.blueprints import store as store_module
from dedo.config import CONTENT_DIR, config

# Every collection the fixtures or the requests write to.
COLLECTIONS = ['games']

GAME_ID = 900000001
OTHER_ID = 900000002
MISSING_ID = 900000000
SLASH_ID = 900000200
GAME_TITLE = "Smoke Game"
OTHER_TITLE = "Other Game"
MISSING_TITLE = "Missing Images Game"
SLASH_TITLE = "Slash A/B Game"
GAME_VENDOR = "Smoke Vendor"
OTHER_VENDOR = "Other Vendor"
MISSING_VENDOR = "Missing Vendor"
SLASH_VENDOR = "Hugo Games A/S"
PAGE_VENDOR = "Page Vendor"

FIXTURE_FILES = {
    os.path.join(CONTENT_DIR, "files", "smoke.jar"): b"PK\x03\x04smoke-jar-fixture",
    os.path.join(CONTENT_DIR, "files", "smoke.jad"): b"MIDlet-Name: Smoke Game\n",
    os.path.join(CONTENT_DIR, "files", "smoke.sis"): b"not a real sis file",
    os.path.join(CONTENT_DIR, "files", "smoke.sisx"): b"not a real sisx file",
    os.path.join(CONTENT_DIR, "images", "splashes", "smoke.png"): b"\x89PNG\r\n\x1a\nsmoke",
    os.path.join(CONTENT_DIR, "images", "screenshots", "smoke.jpg"): b"\xff\xd8\xff\xe0smoke",
    os.path.join(CONTENT_DIR, "images", "splashes", "other-splash.png"): b"\x89PNG\r\n\x1a\nother",
    os.path.join(CONTENT_DIR, "images", "screenshots", "other-shot.jpg"): b"\xff\xd8\xff\xe0other",
    os.path.join(CONTENT_DIR, "images", "banners", f"{GAME_ID}.jpg"): b"\xff\xd8\xff\xe0banner",
}

FIXTURES = [
    {
        "id": GAME_ID,
        "title": GAME_TITLE,
        "vendor": GAME_VENDOR,
        "downloads": 5,
        "date": datetime(2020, 1, 2),
        "banner": True,
        "resolutions": {
            "240x320": {
                "Nokia": [
                    {"type": "jar", "filename": "smoke.jar"},
                    {"type": "jad", "filename": "smoke.jad"},
                    {"type": "sis", "filename": "smoke.sis"},
                    {"type": "sisx", "filename": "smoke.sisx"},
                ]
            },
            "320x240": {"Sony Ericsson": [{"type": "jar", "filename": None}]},
        },
        "splash": {"filename": "smoke.png",
                   "link": "http://dedomil.net/hry_scr/smoke/smoke.png"},
        "screenshot": {"filename": "smoke.jpg",
                       "link": "http://dedomil.net/hry_scr/smoke/smoke.jpg"},
        # U+0019 is not a legal XML 1.0 character and must not reach the page.
        "description": "Line one\x19\nLine two <b>x</b>",
    },
    {
        "id": OTHER_ID,
        "title": OTHER_TITLE,
        "vendor": OTHER_VENDOR,
        "downloads": 50,
        "date": datetime(2021, 2, 3),
        "banner": False,
        "resolutions": {"240x320": {"Nokia": [{"type": "jar"}]}},
        "splash": "other-splash.png",
        "screenshot": "other-shot.jpg",
        "description": "Other game description",
    },
    {
        "id": MISSING_ID,
        "title": MISSING_TITLE,
        "vendor": MISSING_VENDOR,
        "downloads": 1,
        "date": datetime(2019, 1, 1),
        "banner": False,
        "resolutions": {"240x320": {"Nokia": [{"type": "jar"}]}},
        "splash": {"link": "http://dedomil.net/hry_scr/missing/missing.png"},
        "screenshot": {"filename": None, "link": "http://dedomil.net/hry_scr/missing/missing.jpg"},
        "description": "Missing image description",
    },
    {
        "id": SLASH_ID,
        "title": SLASH_TITLE,
        "vendor": SLASH_VENDOR,
        "downloads": 2,
        "date": datetime(2022, 3, 4),
        "banner": False,
        "resolutions": {"240x320": {"Nokia": [{"type": "jar", "filename": "smoke.jar"}]}},
        "splash": None,
        "screenshot": None,
        "description": "Slash game description",
    },
]


CONFIG_FIXTURE = """\
per_page: 10
allow_indexing: false
api_prefix: /api/v1
"""

ROOT_DIR = Path(__file__).resolve().parents[1]


def run_config(extra_env=None, config_text=CONFIG_FIXTURE,
               expression='import dedo.config'):
    """Import dedo.config in a fresh process with only the given Mongo settings."""
    with tempfile.TemporaryDirectory() as directory:
        config_path = Path(directory) / 'config.yaml'
        config_path.write_text(config_text)
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('MONGO_')}
        env.update({'DEDO_CONFIG': str(config_path), 'MONGO_DB': 'dedo_config_check'})
        env.update(extra_env or {})
        return subprocess.run(
            [sys.executable, '-c', expression],
            cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=30,
        )


def check_config_validation():
    """Startup rejects the old URI key and non-ASCII or out-of-range ports."""
    problems = []
    secret = 'do-not-print-this-value'
    obsolete = run_config(config_text=CONFIG_FIXTURE +
                          f'mongodb_uri: "mongodb://operator:{secret}@db.example/live"\n')
    if obsolete.returncode == 0:
        problems.append('a config with mongodb_uri was accepted')
    else:
        if 'ConfigError' not in obsolete.stderr:
            problems.append('mongodb_uri did not raise ConfigError')
        if 'mongodb_uri' not in obsolete.stderr:
            problems.append('mongodb_uri diagnostic does not name the key')
        if secret in obsolete.stderr or 'db.example' in obsolete.stderr:
            problems.append('mongodb_uri diagnostic leaks its value')
        if 'MONGO_DB' not in obsolete.stderr or 'are optional' not in obsolete.stderr:
            problems.append('mongodb_uri diagnostic does not mark the other MONGO_* variables optional')

    for port in ('0', '65536', '²'):
        result = run_config({'MONGO_PORT': port})
        if result.returncode == 0:
            problems.append(f'MONGO_PORT={port!r} was accepted')
        elif 'MONGO_PORT' not in result.stderr:
            problems.append(f'MONGO_PORT={port!r} diagnostic does not name the variable')

    for extra_env in ({}, {'MONGO_PORT': ''}):
        default = run_config(extra_env, expression='import dedo.config; print(dedo.config.MONGO_PORT)')
        if default.returncode != 0:
            problems.append(f'{extra_env or "omitted"} MONGO_PORT failed: {default.stderr.strip()[-200:]}')
        elif default.stdout.strip() != '27017':
            problems.append(f'{extra_env or "omitted"} MONGO_PORT defaulted to '
                            f'{default.stdout.strip()!r}, expected 27017')

    padded = run_config(
        {'MONGO_PORT': ' 27017 '},
        expression='import dedo.config as c; print(c.MONGO_PORT); print(c.MONGO_URI)',
    )
    expected_uri = 'mongodb://localhost:27017/dedo_config_check'
    if padded.returncode != 0:
        problems.append(f'padded MONGO_PORT failed: {padded.stderr.strip()[-200:]}')
    elif padded.stdout.splitlines() != ['27017', expected_uri]:
        problems.append(f'padded MONGO_PORT produced {padded.stdout.splitlines()!r}, '
                        f'expected [\'27017\', {expected_uri!r}]')

    for text in ('canonical_url: "ftp://dedomil.example"',
                 'canonical_url: "https://user:pw@dedomil.example"',
                 'canonical_url: "https://dedomil.example/?q=1"',
                 'canonical_url: 5',
                 'google_site_verification: ""'):
        key = text.split(':')[0]
        result = run_config(config_text=CONFIG_FIXTURE + text + '\n')
        if result.returncode == 0:
            problems.append(f'{text} was accepted')
            continue
        if 'ConfigError' not in result.stderr:
            problems.append(f'{text} did not raise ConfigError')
        if key not in result.stderr:
            problems.append(f'{text} diagnostic does not name the key')
        if 'pw@' in result.stderr:
            problems.append(f'{text} diagnostic leaks the credentials')

    expression = ('from dedo.app import app; from dedo import helpers\n'
                  'with app.test_request_context("/"): '
                  'print(helpers.canonical_url_for("store.games"))')
    for text, expected in (
            ('canonical_url: "https://dedomil.example/dedo/"\n',
             'https://dedomil.example/dedo/games'),
            ('', 'http://localhost/games')):
        result = run_config(config_text=CONFIG_FIXTURE + text, expression=expression)
        if result.returncode != 0:
            problems.append(f'canonical_url_for failed: {result.stderr.strip()[-200:]}')
        elif result.stdout.strip() != expected:
            problems.append(f'canonical_url_for printed {result.stdout.strip()!r}, '
                            f'expected {expected!r}')
    return problems


def check_empty():
    busy = [name for name in COLLECTIONS if db.get_collection(name).count_documents({})]
    if busy:
        sys.exit(f"Refusing to run: these collections already hold documents: {', '.join(busy)}. "
                 "Point MONGO_DB at a fresh database.")
    existing = [path for path in FIXTURE_FILES if os.path.exists(path)]
    if existing:
        sys.exit(f"Refusing to run: fixture files already exist: {', '.join(existing)}")


def seed(cleanup):
    db.create_indexes()

    for path, data in FIXTURE_FILES.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'xb') as destination:
            cleanup.callback(Path(path).unlink, missing_ok=True)
            destination.write(data)

    games = db.get_collection('games')
    documents = [dict(fixture, _id=ObjectId()) for fixture in FIXTURES]
    # Register before writing so a partial insert can be cleaned up too.
    cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
    games.insert_many(documents)


def check_indexes():
    names = {index['name'] for index in db.get_collection('games').list_indexes()}
    expected = {'_id_', 'id_unique', 'vendor', 'downloads_desc', 'banner'}
    missing = sorted(expected - names)
    return [f"missing indexes: {', '.join(missing)}"] if missing else []


def check_vendors():
    vendors = db.get_vendors()
    problems = []
    if vendors != sorted(vendors):
        problems.append(f"vendors are not sorted: {vendors}")
    missing = sorted({GAME_VENDOR, OTHER_VENDOR} - set(vendors))
    if missing:
        problems.append(f"vendors lack: {', '.join(missing)}")
    return problems


def check_cache():
    problems = []

    calls = []

    @cache.ttl_cache(300)
    def sample(value):
        calls.append(value)
        return value

    sample(1)
    sample(1)
    if calls != [1]:
        problems.append(f"ttl_cache did not reuse the entry, calls={calls}")
    sample.cache_clear()
    sample(1)
    if calls != [1, 1]:
        problems.append(f"cache_clear did not drop the entry, calls={calls}")

    games = db.get_collection('games')
    cache.clear()
    baseline = db.get_vendors()
    extra = {'_id': ObjectId(), 'id': GAME_ID + 2, 'vendor': 'Cache Vendor'}
    try:
        games.insert_one(extra)
        cached = db.get_vendors()
    finally:
        games.delete_one({'_id': extra['_id']})
    if cached != baseline:
        problems.append("get_vendors did not serve the cached list")
    cache.clear()
    if 'Cache Vendor' in db.get_vendors():
        problems.append("cache.clear did not reset get_vendors")

    return problems


def check_api_sizes(client, game_url):
    response = client.get(game_url)
    if response.status_code != 200:
        return [f"status {response.status_code}, expected 200"]
    files = (response.get_json() or {}).get('files', {})
    sizes = {file.get('filename'): file.get('size') for files in files.values() for file in files}
    problems = []
    if sizes.get('smoke.jar') in (None, '', '0 Bytes'):
        problems.append(f"smoke.jar size is {sizes.get('smoke.jar')!r}")
    return problems


TOP_50_MIXED = [
    ('String 1469607', '1469607'),
    ('String 9998', '9998'),
    ('Integer 5000', 5000),
    ('Integer 4000', 4000),
    ('Integer 3000', 3000),
    ('Tie A', 1000),
    ('Tie B', 1000),
    ('Tie C', 1000),
    ('Tie D', 1000),
    ('String 999', '999'),
    ('Integer 999', 999),
] + [(f'Count {count}', count) for count in range(900, 852, -1)] + [('Null count', None)]


def check_top_50_limit(client):
    games = db.get_collection('games')
    documents = [
        {'_id': ObjectId(), 'id': OTHER_ID + rank, 'title': title,
         'downloads': downloads, 'date': FIXTURES[0]['date']}
        for rank, (title, downloads) in enumerate(TOP_50_MIXED, start=1)
    ]
    # Numerical order, not BSON type order: strings and integers interleave,
    # equal counts fall back to ascending id (the insertion order here), and
    # null counts sort last.
    expected = [title for title, _ in TOP_50_MIXED[:11]] + [
        f'Count {count}' for count in range(900, 861, -1)
    ]

    def titles(response):
        page = ET.fromstring(response.data)
        return [link.text for link in page.findall('.//{*}div[@class="GMENU"]/{*}a')]

    problems = []
    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
        games.insert_many(documents)
        with patch.dict(config, per_page=50):
            first = client.get('/games/top')
        with patch.dict(config, per_page=12):
            fifth = client.get('/games/top/page/5')

    if first.status_code != 200:
        problems.append(f'page 1 status {first.status_code}, expected 200')
    else:
        found = titles(first)
        if found != expected:
            problems.append(f'expected numerical order {expected}, got {found}')
        if 'Null count' in found:
            problems.append('null count appeared in the Top 50')
    if fifth.status_code != 200:
        problems.append(f'page 5 status {fifth.status_code}, expected 200')
    else:
        found = titles(fifth)
        if found != expected[48:50]:
            problems.append(f'expected ranks 49 and 50 {expected[48:50]}, got {found}')
    return problems


def check_image_filename_normalization():
    """Stored filenames are trimmed before they are turned into URLs."""
    problems = []
    for value in (' smoke.png ', {'filename': ' smoke.png '}):
        result = helpers.image_filename(value)
        if result != 'smoke.png':
            problems.append(f'image_filename({value!r}) returned {result!r}')
    return problems


def check_game_image_links(client):
    problems = []
    cases = [
        (GAME_ID, 'images/splashes/smoke.png', 'images/screenshots/smoke.jpg'),
        (OTHER_ID, 'images/splashes/other-splash.png', 'images/screenshots/other-shot.jpg'),
    ]
    for game_id, splash, screenshot in cases:
        response = client.get(f'/games/{game_id}')
        if response.status_code != 200:
            problems.append(f'game {game_id}: status {response.status_code}')
            continue
        page = ET.fromstring(response.data)
        for block, relative in (('SPLASH', splash), ('SECSCR', screenshot)):
            link = page.find(f'.//{{*}}div[@class="{block}"]/{{*}}a')
            url = link.get('href') if link is not None else None
            if url is None:
                problems.append(f'game {game_id}: no {block} link')
                continue
            expected = '/static/content/' + relative
            if url != expected:
                problems.append(f'game {game_id}: {block} link {url!r}, expected {expected!r}')
                continue
            image = client.get(url)
            if image.status_code != 200:
                problems.append(f'game {game_id}: {url} returned {image.status_code}')
            elif image.data != FIXTURE_FILES[os.path.join(CONTENT_DIR, relative)]:
                problems.append(f'game {game_id}: {url} returned the wrong bytes')

    response = client.get(f'/games/{MISSING_ID}')
    if response.status_code != 200:
        problems.append(f'game {MISSING_ID}: status {response.status_code}')
    else:
        page = ET.fromstring(response.data)
        for block in ('SPLASH', 'SECSCR'):
            if page.find(f'.//{{*}}div[@class="{block}"]/{{*}}a') is not None:
                problems.append(f'game {MISSING_ID}: rendered a {block} link without a filename')
    return problems


def check_slash_routes(client):
    """Slash values use query strings; ordinary values keep the path form."""
    problems = []
    games = db.get_collection('games')
    documents = [
        {'_id': ObjectId(), 'id': OTHER_ID + 100 + number,
         'title': f'Slash Search {number} A/B', 'vendor': OTHER_VENDOR,
         'downloads': 1, 'date': FIXTURES[0]['date'], 'banner': False,
         'resolutions': {'240x320': {'Nokia': [{'type': 'jar'}]}}}
        for number in range(1, 13)
    ]

    def follows(url, path, **expected):
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        return parts.path == path and all(
            query.get(key) == [value] for key, value in expected.items()
        )

    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
        games.insert_many(documents)
        # The vendor list was cached before these temporary rows existed.
        cache.clear()

        # The rendered vendor list links a slash vendor through the query form.
        response = client.get('/games/vendors')
        page = ET.fromstring(response.data)
        links = {link.text: link.get('href')
                 for link in page.findall('.//{*}div[@class="GMENU"]/{*}a')}
        href = links.get(SLASH_VENDOR)
        if href is None:
            problems.append(f'vendor list has no link for {SLASH_VENDOR!r}')
        elif not follows(href, '/games/vendor', name=SLASH_VENDOR):
            problems.append(f'slash vendor link {href!r} is not a /games/vendor?name= link')
        else:
            followed = client.get(href)
            if followed.status_code != 200:
                problems.append(f'following vendor link {href!r} returned {followed.status_code}')
            elif SLASH_TITLE not in followed.get_data(as_text=True):
                problems.append(f'following vendor link {href!r} lacks {SLASH_TITLE!r}')

        # Posting the search form redirects to the query form for a slash query.
        posted = client.post('/games/search', data={'q': 'A/B'})
        location = posted.headers.get('Location', '')
        if posted.status_code != 302:
            problems.append(f'search form returned {posted.status_code}, expected 302')
        elif not follows(location, '/games/search', q='A/B', page='1'):
            problems.append(f'search form redirected to {location!r}, expected /games/search?q=A/B&page=1')

        # Pagination keeps the slash query in the query string and page 2 works.
        # Pin per_page so the assertion holds under any operator configuration.
        with patch.dict(config, per_page=10):
            first = client.get('/games/search?q=A%2FB&page=1')
            if first.status_code != 200:
                problems.append(f'slash search page 1 returned {first.status_code}')
            else:
                page = ET.fromstring(first.data)
                links = [link.get('href') for link in page.findall('.//{*}div[@class="PAGES"]/{*}a')]
                if not any(link and follows(link, '/games/search', q='A/B', page='2') for link in links):
                    problems.append(f'slash search page 1 has no query-form page 2 link: {links}')
                second = client.get('/games/search?q=A%2FB&page=2')
                body = second.get_data(as_text=True)
                if second.status_code != 200:
                    problems.append(f'slash search page 2 returned {second.status_code}')
                elif not any(f'Slash Search {number} A/B' in body for number in range(1, 13)):
                    problems.append('slash search page 2 lacks a temporary result')

        # A vendor name that matches nothing is a Dedo page, not a redirect.
        response = client.get('/games/vendor?name=No%20Such%20Vendor')
        if response.status_code != 404:
            problems.append(f'unknown named vendor returned {response.status_code}, expected 404')
        elif b'Not found' not in response.data:
            problems.append('unknown named vendor did not render the XHTML 404 page')

        # Ordinary values keep the legacy path form, first page and paginated.
        for url in ('/games/search/Smoke', '/games/search/Smoke/page/1',
                    '/games/vendor/Smoke%20Vendor', '/games/vendor/Smoke%20Vendor/page/1'):
            response = client.get(url)
            if response.status_code != 200:
                problems.append(f'legacy URL {url} returned {response.status_code}')
            elif GAME_TITLE not in response.get_data(as_text=True):
                problems.append(f'legacy URL {url} lacks {GAME_TITLE!r}')

    cache.clear()
    return problems


def check_vendor_pagination(client):
    """Both vendor routes page through a vendor's games."""
    games = db.get_collection('games')
    documents = [
        {'_id': ObjectId(), 'id': OTHER_ID + 300 + number,
         'title': f'Page Vendor Game {number:02d}', 'vendor': PAGE_VENDOR,
         'downloads': 1, 'date': FIXTURES[0]['date'], 'banner': False,
         'resolutions': {'240x320': {'Nokia': [{'type': 'jar'}]}}}
        for number in range(1, 13)
    ]
    expected = {f'Page Vendor Game {number:02d}' for number in range(6, 11)}

    problems = []
    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
        games.insert_many(documents)
        with patch.dict(config, per_page=5):
            for url in (f'/games/vendor/{quote(PAGE_VENDOR)}/page/2',
                        f'/games/vendor?name={quote(PAGE_VENDOR)}&page=2'):
                response = client.get(url)
                if response.status_code != 200:
                    problems.append(f'{url} returned {response.status_code}')
                    continue
                page = ET.fromstring(response.data)
                found = {link.text for link in page.findall('.//{*}div[@class="GMENU"]/{*}a')}
                if found != expected:
                    problems.append(f'{url} shows {sorted(found)}, expected {sorted(expected)}')
    return problems


def check_bare_missing_file(client):
    """A missing content file is a bare 404, not a rendered Dedo page."""
    response = client.get('/static/content/files/does-not-exist.sis')
    problems = []
    if response.status_code != 404:
        problems.append(f'status {response.status_code}, expected 404')
    if b'class="NHRY"' in response.data:
        problems.append('missing file rendered the Dedo error page')
    if b'Not Found' not in response.data:
        problems.append('missing file did not return the bare 404 body')
    return problems


def check_healthz_unavailable(client):
    """An unreachable database makes the health check report 503."""
    with patch.object(db, 'ping', side_effect=PyMongoError('unavailable')):
        response = client.get('/healthz')
    problems = []
    if response.status_code != 503:
        problems.append(f'status {response.status_code}, expected 503')
    if response.data != b'db unavailable':
        problems.append(f'body {response.data!r}, expected b"db unavailable"')
    if response.headers.get('Content-Type') != 'text/plain':
        problems.append(f'Content-Type {response.headers.get("Content-Type")!r}')
    if response.headers.get('Cache-Control') != 'no-store':
        problems.append(f'Cache-Control {response.headers.get("Cache-Control")!r}')
    return problems


def check_description_rendering(client):
    """A missing or non-string description must not break the game page."""
    problems = []
    games = db.get_collection('games')
    documents = [
        {'_id': ObjectId(), 'id': OTHER_ID + 200, 'title': 'No Description Game',
         'vendor': OTHER_VENDOR, 'downloads': 1, 'date': FIXTURES[0]['date'],
         'banner': False,
         'resolutions': {'240x320': {'Nokia': [{'type': 'jar'}]}}},
        {'_id': ObjectId(), 'id': OTHER_ID + 201, 'title': 'Numeric Description Game',
         'vendor': OTHER_VENDOR, 'downloads': 1, 'date': FIXTURES[0]['date'],
         'banner': False,
         'resolutions': {'240x320': {'Nokia': [{'type': 'jar'}]}},
         'description': 12345},
    ]

    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
        games.insert_many(documents)
        for document in documents:
            response = client.get(f'/games/{document["id"]}')
            if response.status_code != 200:
                problems.append(f'{document["title"]} returned {response.status_code}')
                continue
            try:
                ET.fromstring(response.data)
            except ET.ParseError as error:
                problems.append(f'{document["title"]}: invalid XML: {error}')

        numeric = client.get(f'/games/{documents[1]["id"]}')
        if b'content="12345"' not in numeric.data:
            problems.append('numeric description was not rendered')
        missing = client.get(f'/games/{documents[0]["id"]}')
        expected = b'content="No Description Game by Other Vendor, a free mobile game."'
        if expected not in missing.data:
            problems.append('missing description did not use the fallback')
    return problems


def check_sitemap_parts(client):
    """Parts stay within the size limit, cover every URL once, and tolerate dateless games."""
    problems = []
    games = db.get_collection('games')
    document = {'_id': ObjectId(), 'id': OTHER_ID + 300, 'title': 'Dateless Game',
                'vendor': OTHER_VENDOR, 'downloads': 1, 'banner': False,
                'resolutions': {'240x320': {'Nokia': [{'type': 'jar'}]}}}
    ns = '{http://www.sitemaps.org/schemas/sitemap/0.9}'

    def locs(response):
        return [loc.text for loc in ET.fromstring(response.data).iter(ns + 'loc')]

    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': document['_id']})
        cleanup.callback(cache.clear)
        games.insert_one(document)
        cache.clear()

        whole = locs(client.get('/sitemap/1.xml'))
        with patch.object(store_module, 'SITEMAP_URLS_PER_FILE', 5):
            index = locs(client.get('/sitemap.xml'))
            if len(index) < 2:
                problems.append(f'index lists {len(index)} parts, expected several')
            combined = []
            for number in range(1, len(index) + 1):
                response = client.get(f'/sitemap/{number}.xml')
                if response.status_code != 200:
                    problems.append(f'part {number} returned {response.status_code}')
                    continue
                urls = list(ET.fromstring(response.data).iter(ns + 'url'))
                if len(urls) > 5:
                    problems.append(f'part {number} has {len(urls)} urls')
                combined += locs(response)
            if combined != whole:
                problems.append('the parts together do not list the same URLs as one file')

        base = whole[0].rsplit('/games', 1)[0]
        for url in ET.fromstring(client.get('/sitemap/1.xml').data).iter(ns + 'url'):
            if url.find(ns + 'loc').text == f'{base}/games/{document["id"]}/screens':
                if url.find(ns + 'lastmod') is not None:
                    problems.append('dateless game has a lastmod')
                break
        else:
            problems.append('dateless game is missing from the sitemap')
    return problems


def check_negative_pages(client):
    """Negative and past-the-end pages redirect on every listing."""
    problems = []
    cases = [
        ('/games/search?q=A%2FB&page=-1', '/games/search?q=A/B'),
        ('/games/search?q=A%2FB&page=0', '/games/search?q=A/B'),
        ('/games/search?q=A%2FB&page=99', '/games/search?q=A/B'),
        ('/games/vendor?name=Smoke+Vendor&page=-1', '/games/vendor?name=Smoke+Vendor'),
        ('/games/vendor?name=Smoke+Vendor&page=0', '/games/vendor?name=Smoke+Vendor'),
        ('/games/vendor?name=Smoke+Vendor&page=99', '/games/vendor?name=Smoke+Vendor'),
        ('/games/search/Smoke/page/-1', '/games/search/Smoke'),
        ('/games/search/Smoke/page/99', '/games/search/Smoke'),
        ('/games/vendor/Smoke%20Vendor/page/-1', '/games/vendor/Smoke%20Vendor'),
        ('/games/vendor/Smoke%20Vendor/page/99', '/games/vendor/Smoke%20Vendor'),
        ('/games/top/page/-1', '/games/top'),
        ('/games/top/page/99', '/games/top'),
        ('/games/vendors/page/-1', '/games/vendors'),
        ('/games/vendors/page/99', '/games/vendors'),
        ('/games/browse/page/-1', '/games/browse'),
        ('/games/browse/page/99', '/games/browse'),
        ('/games/screen/240x320/page/-1', '/games/screen/240x320'),
        ('/games/screen/240x320/page/99', '/games/screen/240x320'),
    ]

    # Pin per_page so "past the end" means the same page under any operator config.
    with patch.dict(config, per_page=10):
        for path, location in cases:
            response = client.get(path)
            if response.status_code != 302:
                problems.append(f'{path} returned {response.status_code}, expected 302')
            elif response.headers.get('Location') != location:
                problems.append(f'{path} redirected to {response.headers.get("Location")!r}, '
                                f'expected {location!r}')
    return problems


class Runner:
    def __init__(self):
        self.failures = 0
        self.count = 0

    def report(self, label, problems):
        if problems:
            self.failures += 1
            print(f"FAIL {label}: {'; '.join(problems)}")
        else:
            print(f"ok   {label}")

    def verify(self, label, check):
        self.count += 1
        try:
            problems = check() or []
        except Exception:
            problems = ["raised:\n" + traceback.format_exc()]
        self.report(label, problems)

    def check(self, client, method, path, status, contains=None, location=None,
              location_exact=None, data=None, lacks=None, api=False, headers=None,
              json_body=None, json_keys=None, json_contains=None, result_title=None,
              body_equals=None, xml=False):
        self.count += 1
        label = f"{method} {path}"
        try:
            response = client.open(path, method=method, data=data, json=json_body)
            body = response.get_data()
            problems = []
            statuses = (status,) if isinstance(status, int) else tuple(status)
            if response.status_code not in statuses:
                expected = "/".join(str(value) for value in statuses)
                problems.append(f"status {response.status_code}, expected {expected}")
            for text in ([contains] if isinstance(contains, (str, bytes)) else contains or []):
                needle = text.encode() if isinstance(text, str) else text
                if needle not in body:
                    problems.append(f"body lacks {text!r}")
            for text in ([lacks] if isinstance(lacks, (str, bytes)) else lacks or []):
                needle = text.encode() if isinstance(text, str) else text
                if needle in body:
                    problems.append(f"body has {text!r}")
            if body_equals is not None and body != body_equals:
                problems.append("body does not match the fixture bytes")
            # Every page Dedo renders is XHTML Mobile Profile, so it must be
            # well-formed XML. Redirect bodies (and Werkzeug's own errors) are
            # not rendered by Dedo and are skipped.
            if body and (xml or (response.mimetype == 'text/html' and response.status_code in (200, 404, 500))):
                try:
                    ET.fromstring(body)
                except ET.ParseError as error:
                    problems.append(f"invalid XML: {error}")
            if location is not None and location not in response.headers.get('Location', ''):
                problems.append(f"Location {response.headers.get('Location')!r} lacks {location!r}")
            if location_exact is not None and response.headers.get('Location') != location_exact:
                problems.append(f"Location {response.headers.get('Location')!r}, expected {location_exact!r}")
            if api or json_keys is not None or json_contains is not None or result_title is not None:
                try:
                    payload = response.get_json()
                except ValueError as error:
                    problems.append(f"invalid JSON: {error}")
                else:
                    if api:
                        if payload is None:
                            problems.append("no JSON body")
                        if response.mimetype != 'application/json':
                            problems.append(f"Content-Type {response.content_type!r}")
                    if json_keys is not None:
                        if not isinstance(payload, dict):
                            problems.append(f"expected a JSON object, got {type(payload).__name__}")
                        else:
                            missing = [key for key in json_keys if key not in payload]
                            if missing:
                                problems.append(f"missing JSON keys {missing}")
                    if json_contains is not None:
                        values = payload if isinstance(payload, list) else (payload or {}).get('results', [])
                        if json_contains not in values:
                            problems.append(f"JSON body lacks {json_contains!r}")
                    if result_title is not None:
                        titles = [result.get('title') for result in (payload or {}).get('results', [])]
                        if result_title not in titles:
                            problems.append(f"results lack {result_title!r}, got {titles}")
            for name, value in (headers or {}).items():
                if response.headers.get(name) != value:
                    problems.append(f"{name} {response.headers.get(name)!r}, expected {value!r}")
        except Exception:
            problems = ["raised:\n" + traceback.format_exc()]

        self.report(label, problems)


def run_checks():
    run = Runner()
    run.verify('config validation', check_config_validation)
    api_prefix = config['api_prefix'].rstrip('/')
    api_game_url = f'{api_prefix}/game/?id={GAME_ID}&resolution=240x320'
    # The vendor list is sorted, so a small per_page puts Other Vendor on a later page.
    vendor_page = db.get_vendors().index(OTHER_VENDOR) // config['per_page'] + 1
    per_page = config['per_page']
    last_top_page = (len(FIXTURES) + per_page - 1) // per_page
    last_top_url = '/games/top' if last_top_page == 1 else f'/games/top/page/{last_top_page}'

    canonical_base = (config.get('canonical_url') or 'http://localhost').rstrip('/')

    def check_meta_description():
        problems = []
        long = helpers.meta_description('word ' * 100)
        if len(long) > 160 or not long.endswith('...'):
            problems.append(f'long description came back as {long!r}')
        if helpers.meta_description(None, 'fb') != 'fb':
            problems.append('None did not use the fallback')
        if helpers.meta_description(12345) != '12345':
            problems.append('a number was not converted to text')
        return problems

    run.verify('meta description', check_meta_description)

    with app.test_client() as client:
        run.check(client, 'GET', '/', 301, location='/games')
        run.check(client, 'GET', '/games', 200, contains=f'/games/{GAME_ID}/screens')
        run.check(client, 'GET', f'/games/{GAME_ID}?page=3&x=1', 200,
                  contains=[f'<link rel="canonical" href="{canonical_base}/games/{GAME_ID}" />',
                            f'<meta property="og:url" content="{canonical_base}/games/{GAME_ID}" />',
                            f'<meta property="og:image" content="{canonical_base}/static/content/images/splashes/smoke.png" />',
                            '<meta property="og:site_name" content="Dedomil" />',
                            'content="Line one Line two &lt;b&gt;x&lt;/b&gt;"'],
                  lacks='\x19')
        run.check(client, 'GET', f'/games/{SLASH_ID}', 200, lacks='og:image')
        for listing in ('/games/top/page/1', '/games/top/'):
            run.check(client, 'GET', listing, 200,
                      contains=f'href="{canonical_base}/games/top" />')
        run.check(client, 'GET', '/games/vendor?name=Hugo%20Games%20A%2FS&page=1&junk=2', 200,
                  contains='rel="canonical" href="' + canonical_base + '/games/vendor?name=Hugo',
                  lacks=['junk', 'page=1'])
        # Without a slash, the query form names the path form the links use.
        run.check(client, 'GET', '/games/vendor?name=Smoke%20Vendor&page=1', 200,
                  contains=f'<link rel="canonical" href="{canonical_base}/games/vendor/Smoke%20Vendor" />')
        for noindex_path, noindex_status in (('/games/search', 200), ('/games/search/Smoke', 200),
                                             ('/games/999999', 404)):
            run.check(client, 'GET', noindex_path, noindex_status,
                      contains='content="noindex, follow"', lacks='rel="canonical"')
        with patch.dict(config, google_site_verification='smoke-token'):
            run.check(client, 'GET', '/games', 200,
                      contains='<meta name="google-site-verification" content="smoke-token" />')
        if not config.get('google_site_verification'):
            run.check(client, 'GET', '/games', 200, lacks='google-site-verification')
        with patch.object(db, 'get_random_game', return_value=None):
            run.check(client, 'GET', '/games', 200, contains='Search Games', lacks='/images/banners/')

        # Missing games and resolutions must get Dedo's XHTML-MP error page, not
        # a Werkzeug page and never a 500.
        run.check(client, 'GET', '/games/999999', 404, contains='Not found', lacks='Werkzeug')
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/999x999', 404)

        run.check(client, 'GET', f'/games/{GAME_ID}/screens', 200, contains='240x320')
        # The description is escaped before line breaks are added, the illegal
        # control character is dropped, and the head declares the real media
        # type. Every rendered page is parsed as XML by Runner.check.
        run.check(client, 'GET', f'/games/{GAME_ID}', 200,
                  contains=['smoke.sis', 'smoke.sisx', 'Bytes', '&lt;b&gt;x&lt;/b&gt;',
                            'Line one<br/>Line two',
                            'content="text/html; charset=UTF-8"'],
                  lacks=['<b>x</b>', '\x19'])
        with patch.object(helpers, 'file_size', wraps=helpers.file_size) as file_size:
            run.check(client, 'GET', f'/games/{GAME_ID}/screen/240x320', 200, lacks='320x240')
        checked_files = [call.args[0] for call in file_size.call_args_list]
        run.verify('single-resolution file size lookups', lambda: [
            f'expected lookups only for smoke.jar, smoke.jad, smoke.sis and smoke.sisx, got {checked_files}'
        ] if checked_files != ['smoke.jar', 'smoke.jad', 'smoke.sis', 'smoke.sisx'] else [])
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/320x240', 200,
                  contains='href="#" class="bluelink"', lacks='/static/content/files/None')
        run.check(client, 'GET', f'/games/{OTHER_ID}/screen/240x320', 200,
                  contains='href="#" class="bluelink"')
        run.verify('game image links', lambda: check_game_image_links(client))
        run.verify('image filename normalization', check_image_filename_normalization)
        run.verify('description tolerance', lambda: check_description_rendering(client))

        run.check(client, 'GET', '/games/search', 200, contains='name="q"')
        run.check(client, 'POST', '/games/search', 302, location='/games/search/Smoke/page/1',
                  data={'q': 'Smoke'})
        run.check(client, 'POST', '/games/search', 302, location_exact='/', data={'q': ''})
        run.check(client, 'GET', '/games/search/Smoke', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/search/Smoke/page/2', 302, location_exact='/games/search/Smoke')

        # Regex metacharacters and long input must not reach re.compile unescaped:
        # no 500 and no runaway regex. A literal query with no match redirects,
        # while a pattern treated as a regex would match both fixtures.
        run.check(client, 'GET', '/games/search/%28', 302, location='No+matches+found')
        run.check(client, 'GET', '/games/search/.%2A', 302, location='No+matches+found')
        run.check(client, 'GET', '/games/search/' + quote(GAME_TITLE + ' ' * 190), 200,
                  contains=GAME_TITLE)
        # More than 100 non-whitespace characters, all regex metacharacters.
        run.check(client, 'GET', '/games/search/' + quote('(' * 120), 302,
                  location='No+matches+found')
        run.check(client, 'GET', '/games/search/', 200, contains='name="q"')

        run.check(client, 'GET', '/games/top', 200,
                  contains='<title>TOP 50 games • Dedomil</title>')
        run.check(client, 'GET', '/games/top/page/1', 200)
        run.check(client, 'GET', '/games', 200,
                  contains='<title>Free mobile games • Dedomil</title>')
        run.check(client, 'GET', f'/games/{GAME_ID}', 200, contains=[
            '<title>Download Smoke Game game • Dedomil</title>',
            '<meta property="og:title" content="Download Smoke Game game • Dedomil" />'])
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/240x320', 200,
                  contains='<title>Download Smoke Game 240x320 game • Dedomil</title>')
        run.check(client, 'GET', '/games/vendor/Smoke%20Vendor', 200, contains=[
            '<title>Games by Smoke Vendor • Dedomil</title>',
            'content="Free mobile games by Smoke Vendor."'])
        # Out-of-range pages go back to the first/last page instead of 500.
        run.check(client, 'GET', '/games/top/page/0', 302, location_exact='/games/top')
        run.check(client, 'GET', '/games/top/page/99', 302, location_exact=last_top_url)
        run.verify('Top 50 caps the partial final page', lambda: check_top_50_limit(client))
        run.check(client, 'GET', '/games/latest', 200,
                  contains=[OTHER_TITLE, '03.02.2021'], lacks='2021-02-03 00:00:00')

        run.check(client, 'GET', '/games/vendors', 200)
        run.check(client, 'GET', f'/games/vendor/{quote(GAME_VENDOR)}', 200, contains=GAME_TITLE)
        # Both vendor forms report an unknown vendor as a 404.
        run.check(client, 'GET', '/games/vendor/No%20Such%20Vendor', 404, contains='Not found')
        run.verify('slash routing', lambda: check_slash_routes(client))
        run.verify('vendor pagination', lambda: check_vendor_pagination(client))
        run.verify('negative and past-the-end pages', lambda: check_negative_pages(client))

        run.check(client, 'GET', '/games/screens', 200)
        run.check(client, 'GET', '/games/screen/240x320', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/screen/240x320/page/1', 200)
        run.check(client, 'GET', '/games/screen/999x999', 404, contains='Not found')
        run.check(client, 'GET', '/games/screen/999x999/page/2', 404, contains='Not found')
        run.check(client, 'GET', '/games/screen/240x320.Nokia', 404, contains='Not found')

        run.check(client, 'GET', '/games/browse', 200)
        run.check(client, 'GET', '/games/browse/page/1', 200)
        run.check(client, 'GET', '/games/browse/page/0', 302, location_exact='/games/browse')

        run.check(client, 'GET', '/static/css/style.css', 200,
                  headers={'Cache-Control': 'public, max-age=86400'})
        run.check(client, 'GET', '/static/content/files/smoke.jar', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'files', 'smoke.jar')],
                  headers={'Content-Type': 'application/java-archive'})
        run.check(client, 'GET', '/static/content/files/smoke.jad', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'files', 'smoke.jad')],
                  headers={'Content-Type': 'text/vnd.sun.j2me.app-descriptor; charset=utf-8'})
        # Phones pick the installer by Content-Type, so the image must set
        # these itself rather than rely on the host's /etc/mime.types.
        run.check(client, 'GET', '/static/content/files/smoke.sis', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'files', 'smoke.sis')],
                  headers={'Content-Type': 'application/vnd.symbian.install'})
        run.check(client, 'GET', '/static/content/files/smoke.sisx', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'files', 'smoke.sisx')],
                  headers={'Content-Type': 'x-epoc/x-sisx-app'})
        run.check(client, 'GET', '/static/content/images/splashes/smoke.png', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'images', 'splashes', 'smoke.png')])
        run.verify('bare missing content file', lambda: check_bare_missing_file(client))
        if config['allow_indexing']:
            # The disallowed paths carry canonical_url's path prefix, like the Sitemap line.
            robots_prefix = urlsplit(canonical_base).path
            run.check(client, 'GET', '/robots.txt', 200,
                      contains=[f'Disallow: {robots_prefix}{api_prefix}/',
                                f'Disallow: {robots_prefix}/static/content/files/',
                                f'Sitemap: {canonical_base}/sitemap.xml'],
                      lacks='Disallow: /games')
        else:
            run.check(client, 'GET', '/robots.txt', 200, contains='Disallow: /')
        run.check(client, 'GET', '/sitemap.xml', 200, xml=True,
                  contains=['<sitemapindex', f'{canonical_base}/sitemap/1.xml</loc>'])
        run.check(client, 'GET', '/sitemap/1.xml', 200, xml=True, contains=[
            f'{canonical_base}/games/top</loc>',
            f'/games/{GAME_ID}/screens</loc>',
            f'/games/{GAME_ID}/screen/240x320</loc>',
            '/games/vendor/Smoke%20Vendor</loc>',
            '/games/vendor?name=Hugo',
            '/games/screen/240x320</loc>',
            '<lastmod>2020-01-02</lastmod>'],
            lacks=['/games/search', f'<loc>{canonical_base}/</loc>'])
        run.check(client, 'GET', '/sitemap/0.xml', 404)
        run.check(client, 'GET', '/sitemap/99.xml', 404)
        run.verify('sitemap parts', lambda: check_sitemap_parts(client))
        run.check(client, 'GET', '/healthz', 200, body_equals=b'ok',
                  headers={'Content-Type': 'text/plain',
                           'Cache-Control': 'no-store'})
        run.verify('health endpoint without Mongo', lambda: check_healthz_unavailable(client))

        run.check(client, 'GET', f'{api_prefix}/resolutions/', 200, api=True, json_contains='240x320')
        run.check(client, 'GET', f'{api_prefix}/vendors/?page={vendor_page}', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], json_contains=OTHER_VENDOR)
        run.check(client, 'GET', f'{api_prefix}/vendor/?name={quote(GAME_VENDOR)}&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', api_game_url, 200, api=True,
                  json_keys=['title', 'files'])
        run.verify('api file sizes', lambda: check_api_sizes(client, api_game_url))
        run.check(client, 'GET', f'{api_prefix}/game/resolutions/?id={GAME_ID}', 200, api=True,
                  json_contains='240x320')
        run.check(client, 'GET', f'{api_prefix}/search/?q=smoke&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', f'{api_prefix}/resolution/?name=240x320&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)

    run.verify('indexes', check_indexes)
    run.verify('sorted vendors', check_vendors)
    run.verify('ttl cache', check_cache)

    print(f"\n{run.count - run.failures}/{run.count} checks passed")
    return run.failures == 0


def main():
    app.config['TESTING'] = True
    try:
        check_empty()
        with ExitStack() as cleanup:
            seed(cleanup)
            passed = run_checks()
    finally:
        db.client.close()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
