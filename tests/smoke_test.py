"""Request-level smoke test for Dedo.

Run against a throwaway database:

    MONGO_DB=dedo_test python -m tests.smoke_test

The script refuses to run when the games collection is not empty or when any
fixture file already exists, and removes everything it created afterwards.
"""

import os
from datetime import datetime

from dedo import config
from dedo.app import app
from dedo.db import get_collection

CONTENT_DIR = os.path.join(app.static_folder, "content")
GAMES = get_collection("games")

FIXTURE_FILES = {
    "files/smoke.jar": b"PK\x03\x04smoke-jar-fixture",
    "files/smoke.jad": b"MIDlet-Name: Smoke Game\n",
    "images/splashes/smoke.png": b"\x89PNG\r\n\x1a\nsmoke",
    "images/screenshots/smoke.jpg": b"\xff\xd8\xff\xe0smoke",
    "images/banners/900000001.jpg": b"\xff\xd8\xff\xe0banner",
}

FIXTURE_IDS = [900000001, 900000002]

FIXTURES = [
    {
        "id": 900000001,
        "title": "Smoke Game",
        "vendor": "Smoke Vendor",
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
        "id": 900000002,
        "title": "Other Game",
        "vendor": "Other Vendor",
        "downloads": 50,
        "date": datetime(2021, 2, 3),
        "banner": False,
        "resolutions": {"240x320": {"Nokia": [{"type": "jar", "filename": None}]}},
    },
]


def check_empty():
    count = GAMES.count_documents({})
    if count:
        raise SystemExit(
            f"Refusing to run: the {GAMES.name!r} collection already has "
            f"{count} document(s) in database {config.MONGO_DB!r}"
        )

    existing = [
        name
        for name in FIXTURE_FILES
        if os.path.exists(os.path.join(CONTENT_DIR, name))
    ]
    if existing:
        raise SystemExit(
            "Refusing to run: fixture files already exist: " + ", ".join(existing)
        )


def seed():
    GAMES.insert_many(FIXTURES)

    for relative_path, content in FIXTURE_FILES.items():
        target = os.path.join(CONTENT_DIR, relative_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fixture:
            fixture.write(content)


def cleanup():
    GAMES.delete_many({"id": {"$in": FIXTURE_IDS}})

    for relative_path in FIXTURE_FILES:
        try:
            os.remove(os.path.join(CONTENT_DIR, relative_path))
        except FileNotFoundError:
            pass


def check_response(failures, label, response, status=200, contains=None,
                   not_contains=None, location=None):
    if response.status_code != status:
        failures.append(
            f"{label}: expected status {status}, got {response.status_code}"
        )
        return

    if location is not None:
        actual = response.headers.get("Location", "")
        if not actual.endswith(location):
            failures.append(f"{label}: expected Location ending {location!r}, got {actual!r}")

    if contains is not None or not_contains is not None:
        text = response.get_data(as_text=True)
        if contains is not None and contains not in text:
            failures.append(f"{label}: expected body to contain {contains!r}")
        if not_contains is not None and not_contains in text:
            failures.append(f"{label}: expected body not to contain {not_contains!r}")


def check_json(failures, label, response, contains=None, keys=None,
               result_title=None):
    if response.status_code != 200:
        failures.append(f"{label}: expected status 200, got {response.status_code}")
        return

    body = response.get_json()
    if body is None:
        failures.append(f"{label}: expected a JSON body")
        return

    if keys is not None and not isinstance(body, dict):
        failures.append(f"{label}: expected a JSON object, got {type(body).__name__}")
        return

    if keys is not None:
        missing = [key for key in keys if key not in body]
        if missing:
            failures.append(f"{label}: missing JSON keys {missing}")

    if result_title is not None:
        titles = [result.get("title") for result in body.get("results", [])]
        if result_title not in titles:
            failures.append(
                f"{label}: expected results to contain {result_title!r}, got {titles}"
            )

    if contains is not None:
        values = body if isinstance(body, list) else body.get("results", [])
        if contains not in values:
            failures.append(f"{label}: expected {contains!r} in JSON body")


def run_checks():
    failures = []
    client = app.test_client()

    check_response(failures, "GET /", client.get("/"), status=302, location="/games")
    check_response(failures, "GET /games", client.get("/games"),
                   contains="/games/900000001/screens")

    check_response(failures, "GET /games/<id>/screens",
                   client.get("/games/900000001/screens"), contains="240x320")
    check_response(failures, "GET /games/<id>", client.get("/games/900000001"),
                   contains="smoke.jar")
    check_response(failures, "GET /games/<id> size", client.get("/games/900000001"),
                   contains="Bytes")
    check_response(failures, "GET /games/<id>/screen/<res>",
                   client.get("/games/900000001/screen/240x320"),
                   not_contains="320x240")

    check_response(failures, "GET /games/search", client.get("/games/search"),
                   contains='name="q"')
    check_response(failures, "POST /games/search",
                   client.post("/games/search", data={"q": "Smoke"}),
                   status=302, location="/games/search/Smoke/page/1")
    check_response(failures, "POST /games/search empty",
                   client.post("/games/search", data={"q": ""}),
                   status=302, location="/")
    check_response(failures, "GET /games/search/<query>",
                   client.get("/games/search/Smoke"), contains="Smoke Game")
    check_response(failures, "GET /games/search/<query>/page/2",
                   client.get("/games/search/Smoke/page/2"),
                   status=302, location="/games/search/Smoke")

    check_response(failures, "GET /games/top", client.get("/games/top"))
    check_response(failures, "GET /games/top/page/1",
                   client.get("/games/top/page/1"))
    check_response(failures, "GET /games/latest", client.get("/games/latest"),
                   contains="Other Game")

    check_response(failures, "GET /games/vendors", client.get("/games/vendors"))
    check_response(failures, "GET /games/vendor/<vendor>",
                   client.get("/games/vendor/Smoke%20Vendor"), contains="Smoke Game")

    check_response(failures, "GET /games/screens", client.get("/games/screens"))
    check_response(failures, "GET /games/screen/<res>",
                   client.get("/games/screen/240x320"), contains="Smoke Game")
    check_response(failures, "GET /games/screen/<res>/page/1",
                   client.get("/games/screen/240x320/page/1"))

    check_response(failures, "GET /games/browse", client.get("/games/browse"))
    check_response(failures, "GET /games/browse/page/1",
                   client.get("/games/browse/page/1"))

    check_response(failures, "GET /static/css/style.css",
                   client.get("/static/css/style.css"))

    jar = client.get("/static/content/files/smoke.jar")
    if jar.status_code != 200:
        failures.append(
            f"GET /static/content/files/smoke.jar: expected status 200, "
            f"got {jar.status_code}"
        )
    elif jar.data != FIXTURE_FILES["files/smoke.jar"]:
        failures.append(
            "GET /static/content/files/smoke.jar: body does not match fixture bytes"
        )

    check_response(failures, "GET /robots.txt", client.get("/robots.txt"))

    check_json(failures, "GET /api/v1/resolutions/",
               client.get("/api/v1/resolutions/"), contains="240x320")
    check_json(failures, "GET /api/v1/vendors/",
               client.get("/api/v1/vendors/?page=1"),
               keys={"results", "total_pages", "count"}, contains="Smoke Vendor")
    check_json(failures, "GET /api/v1/vendor/",
               client.get("/api/v1/vendor/?name=Smoke+Vendor&page=1"),
               keys={"results", "total_pages", "count"},
               result_title="Smoke Game")
    check_json(failures, "GET /api/v1/game/",
               client.get("/api/v1/game/?id=900000001&resolution=240x320"),
               keys={"title", "files"})
    check_json(failures, "GET /api/v1/game/resolutions/",
               client.get("/api/v1/game/resolutions/?id=900000001"),
               contains="240x320")
    check_json(failures, "GET /api/v1/search/",
               client.get("/api/v1/search/?q=smoke&page=1"),
               keys={"results", "total_pages", "count"},
               result_title="Smoke Game")
    check_json(failures, "GET /api/v1/resolution/",
               client.get("/api/v1/resolution/?name=240x320&page=1"),
               keys={"results", "total_pages", "count"},
               result_title="Smoke Game")

    return failures


def main():
    check_empty()

    failures = []
    try:
        seed()
        failures = run_checks()
    finally:
        cleanup()

    if failures:
        print(f"{len(failures)} failure(s):")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("0 failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
