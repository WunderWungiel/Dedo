# DedoFOSS
Free and open-source rewrite of Dedomil website - source of games for retro phones

Dedo is a Flask application that renders the game catalogue as XHTML Mobile
Profile 1.0 for old phone browsers. It reads games and download links from
MongoDB, serves banners, screenshots, splashes and game files from `content/`,
and exposes a small JSON API under `/api/v1`.

## Running with Docker

Requires Docker with the Compose plugin. Nothing needs to be installed on the
host.

```bash
cp .env.example .env
cp config.yaml.example config.yaml
```

Edit `.env` and set at least `MONGO_PASSWORD`. The database container creates
its root user from `MONGO_USER` and `MONGO_PASSWORD` the first time the volume
is empty, and the app connects with the same values.

Edit `config.yaml` and set `per_page` and `allow_indexing`. The rest of the
file can stay as it is.

```bash
docker compose up -d --build --wait
```

Open <http://127.0.0.1:8080>. `BIND_ADDRESS` and `PORT` in `.env` change the
address the nginx proxy listens on; the default is localhost only. `--wait`
blocks until `db`, `app` and `proxy` are healthy.

The stack has four services: `db` (MongoDB 8.0), `indexes` (a one-shot job that
creates the MongoDB indexes), `app` (gunicorn) and `proxy` (nginx). `db`, `app`
and `proxy` restart automatically; `indexes` runs once per `up`. The app waits
for the index job to finish successfully, so a failed job leaves the site down
and its logs name the problem instead of hiding it. `db` is healthy once an
authenticated ping succeeds over the Compose network, including when the
catalogue is still empty. `config.yaml` and `content/` are mounted read-only
and are not part of the image.

Compose sets the runtime user of `app` and `indexes` from `APP_UID` and
`APP_GID` in `.env`. Set them to a UID/GID that can read `content/` and
`config.yaml`; the image itself is built with UID/GID 1000.

## Running without Docker

Requires Python 3.14 and a reachable MongoDB 8.0 server.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml

export MONGO_DB=dedomil
export MONGO_HOST=localhost
export MONGO_PORT=27017
export MONGO_USER=mongo
export MONGO_PASSWORD=change-me

flask --app dedo.app run --debug
```

The development server listens on <http://127.0.0.1:5000>. For a production
run use gunicorn:

```bash
gunicorn dedo.app:app
```

`gunicorn.conf.py` binds `127.0.0.1:8000` by default, because a host install
is expected to sit behind nginx. Set `GUNICORN_BIND=0.0.0.0:8000` to listen on
all interfaces. `WEB_CONCURRENCY` sets the number of workers (default 4).

## Configuration

Two files hold configuration; neither is in git and neither is in the image.

`config.yaml` (copy it from `config.yaml.example`) holds settings the
application reads at startup:

- `per_page` — games per page, a positive integer.
- `allow_indexing` — `true` or `false`; when false, `/robots.txt` disallows all
  crawlers, and when true the route is not registered.
- `api_prefix` — URL prefix for the JSON API, normally `/api/v1`.
- `content_dir` — directory with game files and images, relative to the repo
  root (default `content`).
- `canonical_url` — optional. The address search engines should index, such as
  `https://dedomil.example` or `https://dedomil.example/dedo`. It must be an
  absolute HTTP(S) URL without credentials, query or fragment. Left out,
  crawler URLs use the address of the request.
- `google_site_verification` — optional. The content value of Google Search
  Console's HTML tag, printed as a meta tag on every page. It must be a
  non-empty string.

`DEDO_CONFIG` can name a different config file, which is useful for a test
configuration:

```bash
DEDO_CONFIG=/etc/dedo/config.yaml flask --app dedo.app run
```

`.env` (copy it from `.env.example`) is read by Docker Compose:

- `BIND_ADDRESS`, `PORT` — address and port published by the nginx proxy.
- `TZ` — time zone for every container.
- `WEB_CONCURRENCY` — gunicorn worker processes in the app container.
- `APP_UID`, `APP_GID` — UID/GID the app containers run as.
- `MONGO_DB`, `MONGO_USER`, `MONGO_PASSWORD` — database name and credentials.
- `MONGO_HOST`, `MONGO_PORT` — only for a run without Docker; Compose sets the
  host to `db` and the port to `27017`.

Outside Docker, export the five `MONGO_*` variables as shown above. `MONGO_DB`
is required; `MONGO_HOST` and `MONGO_PORT` default to `localhost` and `27017`;
`MONGO_USER` and `MONGO_PASSWORD` are optional but must be set together. A
port must be an ASCII decimal number from 1 to 65535 when it is set. A leftover
`mongodb_uri` in `config.yaml` is rejected at startup; the database connection
comes only from the `MONGO_*` variables.

## Maintenance

Create or refresh the MongoDB indexes. The `indexes` service runs this on
every `docker compose up`, and the `app` service waits for it to exit 0 before
it starts. It can also be run by hand through Compose:

```bash
docker compose build app
docker compose run --rm indexes
```

Build the app image first on a fresh checkout: the one-shot job uses the same
image and does not pull one. A failed job prints the duplicate game ids and
blocks startup until the data is fixed.

Without Docker, use the same command from the repo root with the `MONGO_*`
variables exported:

```bash
flask --app dedo.app create-indexes
```

The command is idempotent and lists the indexes it created.

The `db` container restores `db/dump` into the database named by `MONGO_DB`
through `db/import.sh` only when the `mongo_data` volume is empty, on the first
start. Later starts keep the existing data; to restore a dump manually, use
`mongorestore` inside the container.

## Smoke test

Run the smoke test against a throwaway database, from the repo root:

```bash
MONGO_DB=dedo_test python -m tests.smoke_test
```

The script seeds two games and their files, requests every web page and every
frozen API endpoint through the Flask test client, checks the responses, and
deletes the fixtures afterwards. It refuses to run when the `games` collection
already holds documents or when a fixture file already exists, so point it at a
fresh database. It needs a running MongoDB and a `config.yaml`; `DEDO_CONFIG`
can point at a separate test config.

## Upgrading from the old layout

The application used to live in `app/`, with `app/config.yml`,
`app/static/content/` and a Compose file that kept MongoDB data in a
`./mongo-config` bind mount. An old `.env` used
`MONGO_INITDB_ROOT_USERNAME`, `MONGO_INITDB_ROOT_PASSWORD` and
`MONGO_INITDB_DATABASE` instead of the new `MONGO_USER`, `MONGO_PASSWORD` and
`MONGO_DB`.

Before moving anything, find the database the old app actually used. The old
Compose file started MongoDB with the database named by
`MONGO_INITDB_DATABASE`, but the old app connected with the `mongodb_uri` in
`app/config.yml`. Those names can differ. Read the database name from the URI
(the path after the host and port, before any `?`) and compare it with
`MONGO_INITDB_DATABASE` in the old `.env` or Compose file. If the running image
was built earlier, read the config baked into it
(`docker compose exec -T app cat config.yml`); a file edited after the build
may not be what the app used. Keep the database the app used; if the names
differ, set the new `MONGO_DB` to the app's name, or remap the archive as shown
in step 7.

The example Compose file mounted a root `./content` directory over
`/app/static/content`, so check where the real content lives before copying
anything: `ls content` and `ls app/static/content`.

1. Check the MongoDB version, then choose how to keep the data. The new stack
   runs MongoDB 8.0 and cannot start on data files from 7.x or older. With the
   old stack running:

   ```bash
   docker compose exec -T db mongosh --quiet --eval 'db.version()'
   ```

   If that is older than 8.0, use the dump/restore path in step 7; the old
   bind mount cannot be kept. Dump the old database now, while the old stack
   is still running (this is optional for an 8.0 server). Replace the sample
   value with the live database name you found above; do not keep `dedomil`
   just because it is the bundled name:

   ```bash
   OLD_DB='replace-me-with-the-live-database-name'
   docker compose exec -T -e "DUMP_DB=$OLD_DB" db sh -c 'mongodump \
     -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
     --authenticationDatabase admin --db "$DUMP_DB" \
     --archive' > dedo.archive
   ```

   Print the live game count and write it down for step 8:

   ```bash
   docker compose exec -T -e "DUMP_DB=$OLD_DB" db sh -c 'mongosh --quiet \
     -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
     --authenticationDatabase admin \
     --eval "print(db.getSiblingDB(\"$DUMP_DB\").games.countDocuments())"'
   ```

   If the old stack was started with `-f compose.yaml.example`, add the same
   option to the commands in this step and the next one.

2. Stop the old stack:

   ```bash
   docker compose down
   ```

3. Move the old untracked Compose file aside so `git pull` can write the new
   `compose.yaml`:

   ```bash
   mv compose.yaml compose.old.yaml   # skip if there is no compose.yaml
   git pull
   ```

4. Move the configuration to the repo root and drop the keys the application
   no longer reads (`mongodb_uri`, `secret_key`, `proxy`). The database
   connection now comes from the environment.

   ```bash
   mv app/config.yml config.yaml
   ```

   Edit `config.yaml`, remove those three keys, and make sure `per_page`,
   `allow_indexing`, `api_prefix` and `content_dir` are present. Compare with
   `config.yaml.example` if in doubt. The new app rejects a leftover
   `mongodb_uri` with a `ConfigError`, so it will not start until that key is
   gone.

5. Create `.env` from the example:

   ```bash
   mv .env .env.old   # skip if there is no .env
   cp .env.example .env
   ```

   Copy the old database values into the new names:
   `MONGO_INITDB_ROOT_USERNAME` → `MONGO_USER`,
   `MONGO_INITDB_ROOT_PASSWORD` → `MONGO_PASSWORD`, and
   `MONGO_INITDB_DATABASE` → `MONGO_DB`. Use the live database name from the
   pre-flight check for `MONGO_DB` when it differs from
   `MONGO_INITDB_DATABASE`. The credentials must match the ones the database
   already has, because the MongoDB container only creates the root user when
   the volume is empty. Delete `.env.old` once the new stack works.

6. Move the content out of the old package, if it is still there:

   ```bash
   mkdir -p content
   cp -a app/static/content/. content/
   ```

   If the old Compose file already mounted a root `content/` directory, the
   files are already in place and there is nothing to copy. Delete
   `app/static/content` (and the rest of the leftover `app/` directory) once
   downloads from the new site work. The URLs stay the same
   (`/static/content/...`), so no links change. The app container runs as
   `APP_UID` (default 1000), which only needs read access to `content/` and
   `config.yaml`.

7. Keep the database data. Choose one of these paths.

   If the old server was MongoDB 8.0, the old bind mount can be reused by
   adding `compose.override.yaml`:

   ```yaml
   services:
     db:
       volumes:
         - ./mongo-config:/data/db
   ```

   Otherwise, or if you chose the dump, start the new database and restore
   your archive. The archive keeps the namespace it was dumped from. The
   bundled `db/import.sh` maps its own `dedomil.*` namespace into the database
   named by `MONGO_DB`, but `mongorestore` does not do that for your archive:
   without remapping it recreates the old database name. Set `OLD_DB` to the
   same value as step 1 and remap it explicitly:

   ```bash
   OLD_DB='replace-me-with-the-live-database-name'
   docker compose up -d --wait db
   docker compose exec -T -e "DUMP_DB=$OLD_DB" db sh -c 'mongorestore --drop \
     --nsInclude="$DUMP_DB.*" \
     --nsFrom="$DUMP_DB.*" --nsTo="$MONGO_INITDB_DATABASE.*" \
     -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
     --authenticationDatabase admin --archive' < dedo.archive
   ```

8. Start the new stack and check it:

   ```bash
   docker compose up -d --build --wait
   docker compose ps -a
   ```

   `app`, `proxy` and `db` must be healthy and `indexes` should have exited 0.
   The app waits for the index job, so a failed job stops startup; inspect it
   with `docker compose logs indexes`.

   If you restored an archive in step 7, compare the restored game count with
   the count from step 1; a wrong or non-matching namespace restores silently,
   so the count is the check that catches it:

   ```bash
   docker compose exec -T db sh -c 'mongosh --quiet \
     -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" \
     --authenticationDatabase admin \
     --eval "print(db.getSiblingDB(process.env.MONGO_INITDB_DATABASE).games.countDocuments())"'
   ```

   Do not continue until it matches the count you printed after the dump.

9. The `indexes` service runs as a dependency of `app`, so a normal `up`
   creates or refreshes the indexes first. If you restored data after the
   stack was already running, run the job again:

   ```bash
   docker compose build app
   docker compose run --rm indexes
   ```

Once downloads and the site work, remove `app/`, `compose.old.yaml`,
`dedo.archive` and `.env.old`.
