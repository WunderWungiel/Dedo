# Dedo

A free and open-source rewrite of the Dedomil website, a source of games for retro phones.

It's a Flask app backed by MongoDB. Game files and images live in `content/`.

## Running with Docker

```sh
cp .env.example .env
cp config.yaml.example config.yaml
docker compose up -d --build --wait
```

Before the first start:

- In `.env`, set a real `MONGO_PASSWORD`. The other values have working defaults, and each one is explained in the file.
- In `config.yaml`, set `per_page` and `allow_indexing`. The rest can stay as it is.
- The app runs as UID 1000 and only needs to read `content/` and `config.yaml`. To use another UID, set `APP_UID` and `APP_GID` in `.env`.

The site then listens on `127.0.0.1:8080` (nginx), which you can change with `BIND_ADDRESS` and `PORT`. It's meant to sit behind your own reverse proxy (with HTTPS). On the first start, MongoDB restores the bundled catalogue from `db/dump` into `MONGO_DB`. Later starts keep the existing data.

The stack has four services: `db` (MongoDB 9.0), `indexes` (a one-shot job that creates the indexes), `app` (gunicorn) and `proxy` (nginx). The app waits for `indexes` to succeed, so a failed job leaves the site down. `docker compose logs indexes` shows why.

To change something in `compose.yaml` only on your machine, put it in a `compose.override.yaml`.

## Running without Docker

You need Python 3.14 and a MongoDB 9.0 server.

```sh
pip install -r requirements.txt
cp config.yaml.example config.yaml
export MONGO_DB=dedomil MONGO_HOST=localhost MONGO_PORT=27017 MONGO_USER=mongo MONGO_PASSWORD=...
flask --app dedo.app create-indexes
flask --app dedo.app run --debug
```

`MONGO_DB` is required. `MONGO_HOST` and `MONGO_PORT` default to `localhost` and `27017`. `MONGO_USER` and `MONGO_PASSWORD` are optional, but must be set together. The database connection comes only from these variables, and a leftover `mongodb_uri` in `config.yaml` is rejected at startup.

Run commands from the repo root. For production, use `gunicorn dedo.app:app`, which reads `gunicorn.conf.py` and listens on `127.0.0.1:8000`. Put a reverse proxy in front of it. Change the address with `GUNICORN_BIND` and the worker count with `WEB_CONCURRENCY`.

`create-indexes` is idempotent. Docker runs it for you on every `up`.

## Configuration

`config.yaml` (not in git) is read at startup. `DEDO_CONFIG` points at a different file.

- `per_page`: games per page.
- `allow_indexing`: `true` or `false`, see below.
- `api_prefix`: URL prefix of the JSON API, normally `/api/v1`.
- `content_dir`: directory with game files and images (default `content`).
- `canonical_url`: optional. The address search engines should index, such as `https://dedomil.example` or `https://dedomil.example/dedo`. Without it, the address of the request is used.
- `google_site_verification`: optional. The `content` value of Search Console's HTML tag, printed as a meta tag on every page.

## Search engines

`allow_indexing` decides what crawlers get:

- `false`: `/robots.txt` is `dedo/static/robots.txt`, which disallows everything.
- `true`: `/robots.txt` is generated. It blocks the JSON API and `/static/content/files/` (game downloads), and points at `/sitemap.xml`.

`/sitemap.xml` is an index over `/sitemap/<n>.xml` parts of at most 25,000 URLs each. They list the listing pages, vendors, resolutions and every game's pages, with the game's date as `lastmod`.

All URLs given to crawlers use `canonical_url`. The disallowed paths carry its path prefix. Crawlers only read `/robots.txt` at the root of the host, so a deployment under a prefix such as `/dedo` must have the proxy serve it there.

## Smoke test

There is no test suite, but there is a script that requests every page and API endpoint and checks the responses:

```sh
MONGO_DB=dedo_test python -m tests.smoke_test
```

Run it against an empty, throwaway database. It refuses to start if the `games` collection already holds documents. It seeds its own games and files, and removes them when it finishes. It needs a running MongoDB and a `config.yaml`.
