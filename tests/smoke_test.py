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
import sys
import traceback
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch
from xml.etree import ElementTree as ET

from bson import ObjectId

from dedo import cache, db
from dedo.app import app
from dedo.config import CONTENT_DIR, config

# Every collection the fixtures or the requests write to.
COLLECTIONS = ['games']

GAME_ID = 900000001
OTHER_ID = 900000002
GAME_TITLE = "Smoke Game"
OTHER_TITLE = "Other Game"
GAME_VENDOR = "Smoke Vendor"
OTHER_VENDOR = "Other Vendor"

FIXTURE_FILES = {
    os.path.join(CONTENT_DIR, "files", "smoke.jar"): b"PK\x03\x04smoke-jar-fixture",
    os.path.join(CONTENT_DIR, "files", "smoke.jad"): b"MIDlet-Name: Smoke Game\n",
    os.path.join(CONTENT_DIR, "images", "splashes", "smoke.png"): b"\x89PNG\r\n\x1a\nsmoke",
    os.path.join(CONTENT_DIR, "images", "screenshots", "smoke.jpg"): b"\xff\xd8\xff\xe0smoke",
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
                ]
            },
            "320x240": {"Sony Ericsson": [{"type": "jar", "filename": None}]},
        },
        "splash": "smoke.png",
        "screenshot": "smoke.jpg",
        "description": "Line one\nLine two <b>x</b>",
    },
    {
        "id": OTHER_ID,
        "title": OTHER_TITLE,
        "vendor": OTHER_VENDOR,
        "downloads": 50,
        "date": datetime(2021, 2, 3),
        "banner": False,
        "resolutions": {"240x320": {"Nokia": [{"type": "jar", "filename": None}]}},
    },
]


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


def check_api_sizes(client):
    response = client.get(f'/api/v1/game/?id={GAME_ID}&resolution=240x320')
    if response.status_code != 200:
        return [f"status {response.status_code}, expected 200"]
    files = (response.get_json() or {}).get('files', {})
    sizes = {file.get('filename'): file.get('size') for files in files.values() for file in files}
    problems = []
    if sizes.get('smoke.jar') in (None, '', '0 Bytes'):
        problems.append(f"smoke.jar size is {sizes.get('smoke.jar')!r}")
    return problems


def check_top_50_limit(client):
    games = db.get_collection('games')
    documents = [
        {'_id': ObjectId(), 'id': OTHER_ID + rank, 'title': f'Rank {rank}',
         'downloads': 1000 - rank, 'date': FIXTURES[0]['date']}
        for rank in range(1, 61)
    ]
    with ExitStack() as cleanup:
        cleanup.callback(games.delete_many, {'_id': {'$in': [document['_id'] for document in documents]}})
        games.insert_many(documents)
        with patch.dict(config, per_page=12):
            response = client.get('/games/top/page/5')

    if response.status_code != 200:
        return [f'status {response.status_code}, expected 200']
    page = ET.fromstring(response.data)
    titles = [link.text for link in page.findall('.//{*}div[@class="GMENU"]/{*}a')]
    return [f'expected ranks 49 and 50, got {titles}'] if titles != ['Rank 49', 'Rank 50'] else []


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
              body_equals=None):
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
            if body and response.mimetype == 'text/html' and response.status_code in (200, 404, 500):
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

    with app.test_client() as client:
        run.check(client, 'GET', '/', 302, location='/games')
        run.check(client, 'GET', '/games', 200, contains=f'/games/{GAME_ID}/screens')
        with patch.object(db, 'get_random_game', return_value=None):
            run.check(client, 'GET', '/games', 200, contains='Search Games', lacks='/images/banners/')

        # Missing games and resolutions must get Dedo's XHTML-MP error page, not
        # a Werkzeug page and never a 500.
        run.check(client, 'GET', '/games/999999', 404, contains='Not found', lacks='Werkzeug')
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/999x999', 404)

        run.check(client, 'GET', f'/games/{GAME_ID}/screens', 200, contains='240x320')
        # The description is escaped before line breaks are added.
        run.check(client, 'GET', f'/games/{GAME_ID}', 200,
                  contains=['smoke.jar', 'Bytes', '&lt;b&gt;x&lt;/b&gt;', 'Line one<br/>Line two'],
                  lacks='<b>x</b>')
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/240x320', 200, lacks='320x240')

        run.check(client, 'GET', '/games/search', 200, contains='name="q"')
        run.check(client, 'POST', '/games/search', 302, location='/games/search/Smoke/page/1',
                  data={'q': 'Smoke'})
        run.check(client, 'POST', '/games/search', 302, location_exact='/', data={'q': ''})
        run.check(client, 'GET', '/games/search/Smoke', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/search/Smoke/page/2', 302, location_exact='/games/search/Smoke')

        # Regex metacharacters and long input must not reach re.compile unescaped:
        # no 500 and no runaway regex. A query with no match redirects, as before.
        run.check(client, 'GET', '/games/search/%28', (200, 302))
        run.check(client, 'GET', '/games/search/.%2A', (200, 302))
        run.check(client, 'GET', '/games/search/' + quote(GAME_TITLE + ' ' * 190), 200,
                  contains=GAME_TITLE)
        run.check(client, 'GET', '/games/search/', 200, contains='name="q"')

        run.check(client, 'GET', '/games/top', 200)
        run.check(client, 'GET', '/games/top/page/1', 200)
        # Out-of-range pages go back to the first/last page instead of 500.
        run.check(client, 'GET', '/games/top/page/0', 302, location_exact='/games/top')
        run.check(client, 'GET', '/games/top/page/99', 302, location_exact='/games/top')
        run.verify('Top 50 caps the partial final page', lambda: check_top_50_limit(client))
        run.check(client, 'GET', '/games/latest', 200, contains=OTHER_TITLE)

        run.check(client, 'GET', '/games/vendors', 200)
        run.check(client, 'GET', f'/games/vendor/{quote(GAME_VENDOR)}', 200, contains=GAME_TITLE)

        run.check(client, 'GET', '/games/screens', 200)
        run.check(client, 'GET', '/games/screen/240x320', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/screen/240x320/page/1', 200)

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
        run.check(client, 'GET', '/static/content/images/splashes/smoke.png', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'images', 'splashes', 'smoke.png')])
        run.check(client, 'GET', '/robots.txt', 200)
        run.check(client, 'GET', '/healthz', 200, body_equals=b'ok',
                  headers={'Content-Type': 'text/plain',
                           'Cache-Control': 'no-store'})

        run.check(client, 'GET', '/api/v1/resolutions/', 200, api=True, json_contains='240x320')
        run.check(client, 'GET', '/api/v1/vendors/?page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], json_contains=GAME_VENDOR)
        run.check(client, 'GET', f'/api/v1/vendor/?name={quote(GAME_VENDOR)}&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', f'/api/v1/game/?id={GAME_ID}&resolution=240x320', 200, api=True,
                  json_keys=['title', 'files'])
        run.verify('api file sizes', lambda: check_api_sizes(client))
        run.check(client, 'GET', f'/api/v1/game/resolutions/?id={GAME_ID}', 200, api=True,
                  json_contains='240x320')
        run.check(client, 'GET', '/api/v1/search/?q=smoke&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', '/api/v1/resolution/?name=240x320&page=1', 200, api=True,
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
