#!/usr/bin/env python3
"""Request every route once and check the responses.

Run it against a throwaway database:

    MONGO_DB=dedo_test python -m tests.smoke_test

The script fills the empty games collection with a small set of fixtures and
writes the files they reference under the content directory, requests each web
page and the frozen JSON API through the Flask test client, then deletes the
fixture documents and files. It refuses to run if the games collection already
holds documents or a fixture file already exists, so it can't touch real data.

Run it from the repo root. DEDO_CONFIG can name a config file other than the
repo root's config.yaml.

Exit status is 0 when every check passes and 1 otherwise.
"""

import os
import sys
import traceback
from datetime import datetime
from urllib.parse import quote
from xml.etree import ElementTree as ET

from dedo import db
from dedo.app import app

CONTENT_DIR = os.path.join(app.static_folder, "content")

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


def seed():
    for path, data in FIXTURE_FILES.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'xb') as destination:
            destination.write(data)

    db.get_collection('games').insert_many(FIXTURES)


def cleanup():
    db.get_collection('games').delete_many({'id': {'$in': [GAME_ID, OTHER_ID]}})
    for path in FIXTURE_FILES:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


class Runner:
    def __init__(self):
        self.failures = 0
        self.count = 0

    def check(self, client, method, path, status, contains=None, xml=False, location=None,
              location_exact=None, data=None, lacks=None, api=False, headers=None,
              json_body=None, json_keys=None, json_contains=None, result_title=None,
              body_equals=None):
        self.count += 1
        label = f"{method} {path}"
        try:
            response = client.open(path, method=method, data=data, json=json_body)
            body = response.get_data()
            problems = []
            if response.status_code != status:
                problems.append(f"status {response.status_code}, expected {status}")
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
            if xml:
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

        if problems:
            self.failures += 1
            print(f"FAIL {label}: {'; '.join(problems)}")
        else:
            print(f"ok   {label}")


def run_checks():
    run = Runner()

    with app.test_client() as client:
        run.check(client, 'GET', '/', 302, location='/games')
        run.check(client, 'GET', '/games', 200, contains=f'/games/{GAME_ID}/screens')

        run.check(client, 'GET', f'/games/{GAME_ID}/screens', 200, contains='240x320')
        run.check(client, 'GET', f'/games/{GAME_ID}', 200, contains=['smoke.jar', 'Bytes'])
        run.check(client, 'GET', f'/games/{GAME_ID}/screen/240x320', 200, lacks='320x240')

        run.check(client, 'GET', '/games/search', 200, contains='name="q"')
        run.check(client, 'POST', '/games/search', 302, location=f'/games/search/Smoke/page/1',
                  data={'q': 'Smoke'})
        run.check(client, 'POST', '/games/search', 302, location_exact='/', data={'q': ''})
        run.check(client, 'GET', '/games/search/Smoke', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/search/Smoke/page/2', 302, location_exact='/games/search/Smoke')

        run.check(client, 'GET', '/games/top', 200)
        run.check(client, 'GET', '/games/top/page/1', 200)
        run.check(client, 'GET', '/games/latest', 200, contains=OTHER_TITLE)

        run.check(client, 'GET', '/games/vendors', 200)
        run.check(client, 'GET', f'/games/vendor/{quote(GAME_VENDOR)}', 200, contains=GAME_TITLE)

        run.check(client, 'GET', '/games/screens', 200)
        run.check(client, 'GET', '/games/screen/240x320', 200, contains=GAME_TITLE)
        run.check(client, 'GET', '/games/screen/240x320/page/1', 200)

        run.check(client, 'GET', '/games/browse', 200)
        run.check(client, 'GET', '/games/browse/page/1', 200)

        run.check(client, 'GET', '/static/css/style.css', 200)
        run.check(client, 'GET', '/static/content/files/smoke.jar', 200,
                  body_equals=FIXTURE_FILES[os.path.join(CONTENT_DIR, 'files', 'smoke.jar')])
        run.check(client, 'GET', '/robots.txt', 200)

        run.check(client, 'GET', '/api/v1/resolutions/', 200, api=True, json_contains='240x320')
        run.check(client, 'GET', '/api/v1/vendors/?page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], json_contains=GAME_VENDOR)
        run.check(client, 'GET', f'/api/v1/vendor/?name={quote(GAME_VENDOR)}&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', f'/api/v1/game/?id={GAME_ID}&resolution=240x320', 200, api=True,
                  json_keys=['title', 'files'])
        run.check(client, 'GET', f'/api/v1/game/resolutions/?id={GAME_ID}', 200, api=True,
                  json_contains='240x320')
        run.check(client, 'GET', '/api/v1/search/?q=smoke&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)
        run.check(client, 'GET', '/api/v1/resolution/?name=240x320&page=1', 200, api=True,
                  json_keys=['results', 'total_pages', 'count'], result_title=GAME_TITLE)

    print(f"\n{run.count - run.failures}/{run.count} checks passed")
    return run.failures == 0


def main():
    app.config['TESTING'] = True
    check_empty()
    try:
        seed()
        passed = run_checks()
    finally:
        cleanup()
        db.client.close()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
