# Dedo Refactor Follow-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the catalogue, old-phone compatibility, and deployment issues found when comparing Dedo at `656f275a` with Wunderland Store at `06269c6`.

**Architecture:** Keep the existing Flask routes, MongoDB catalogue, content mounts, and Compose services. Fix catalogue handling at the web rendering and ranking boundaries, then verify the upgrade and startup paths in a disposable Compose project. Use real dump records to supplement the existing synthetic fixtures.

**Tech stack:** Python 3.14, Flask 3.1.3, PyMongo 4.16.0, MongoDB 8.0, Gunicorn, nginx, Docker Compose, and the existing smoke runner.

**Spec:** [Refactor design](../specs/2026-11-22-dedo-refactor-design.md) and [implementation plan](2026-11-22-dedo-refactor.md). The [earlier review](2026-11-22-dedo-refactor-review.md) is a historical snapshot through `ff6ff078`. This plan uses the later audit through `656f275a`.

## Global constraints

- Keep existing public URLs and the `/static/content/...` prefix. Keep web pages usable in XHTML Mobile Profile 1.0 without JavaScript. Serve them as `text/html; charset=UTF-8`.
- Preserve the existing indexing default, titles, crawler policy, and API prefix. Canonical URLs, sitemap, metadata for crawlers, and JSON API feature work remain deferred.
- Keep catalogue records and legacy API payload fields in their existing formats. Record API compatibility differences and test the agreed behavior separately from storefront changes.
- Use the existing smoke runner and runtime dependencies. Use disposable databases, Compose projects, and content directories for verification.

## Review focus

- A bundled game has image objects, while some installations and the smoke suite use strings. Both forms should produce a local URL when a filename exists.
- The bundled catalogue stores counts as strings and has one null count. Top 50 should rank numerically and stop at 50 even on a partial page.
- Symbian installers must have the expected HTTP types in the built image.
- Existing catalogue data includes slashes and an XML-invalid character. The web routes and rendered pages should handle both.
- An initialized MongoDB with zero games should be ready. An old YAML URI that disagrees with the old Compose settings must be caught before the operator switches data sources.

## Task 1 — Render images from the catalogue's stored filenames

**Files** — `dedo/helpers.py`, `dedo/app.py`, `dedo/templates/game.html`, `tests/smoke_test.py`.

- [x] Update game 900000001's smoke fixture to use image objects with `filename` and `link`, as in bundled game 4. Add string-valued image coverage on the other fixture and a case for a missing filename. In a test such as `check_game_image_links(client)`, read the splash and screenshot URLs from the rendered page, follow them, and assert the fixture bytes and HTTP 200.
- [x] Run `MONGO_DB=dedo_test python -m tests.smoke_test` on a disposable database. Expect the object-backed links to fail on the current template.
- [x] Add `image_filename(value: str | dict | None) -> str | None` in `dedo/helpers.py` and register it as a template filter. For a string use its value, and for a mapping use its `filename`. Hide the link when the resulting filename is empty. Build splash and screenshot links through the existing `content` endpoint.
- [x] Rerun the smoke suite and render bundled game 4 in a scratch catalogue with both named files present. Both rendered links should resolve. Commit the image fix.

## Task 2 — Rank Top 50 by numerical download counts

**Files** — `dedo/db.py`, `dedo/blueprints/store.py`, `tests/smoke_test.py`.

- [x] Extend `check_top_50_limit(client)` with mixed BSON types, including string counts `"999"`, `"9998"`, `"1469607"`, an integer count, a null count, and a tie. Assert numerical order, stable order for equal values, and only ranks 49 and 50 on page 5 with `per_page: 12`.
- [x] Run the smoke suite and confirm that the mixed-type ordering assertion fails.
- [x] Add the storefront query `get_top_games(page: int, limit: int = 50) -> list[dict]` in `dedo/db.py`. Use MongoDB `$convert` to a temporary 64-bit integer sort field with zero for invalid or null values. Sort by that field descending and ID ascending, cap the ranked set at 50, then paginate and exclude the temporary field and resolutions from returned rows. Keep `count_games(limit=50)` for pagination totals. Keep the persisted `downloads` value and the shared legacy API queries intact.
- [x] Run the smoke suite and check `/games/top` against the restored dump. The first result should be *Real Football 2018* with 1,469,607 downloads. Check the query against the full dump for acceptable latency and record the timing. Commit the ranking fix.

## Task 3 — Complete installer types and XHTML compatibility

**Files** — `dedo/app.py`, `dedo/helpers.py`, `dedo/templates/base.html`, `tests/smoke_test.py`.

- [x] Add fixture downloads whose headers must be `application/vnd.symbian.install` for `.sis` and `x-epoc/x-sisx-app` for `.sisx`. Add a description containing `U+0019` alongside markup and a newline. Assert the game response parses as XML, retains the escaped markup and line break, and declares `text/html; charset=UTF-8` in its head. Run the smoke suite and record the failures.
- [x] Extend and rename the explicit download types map in `dedo/app.py`, keeping the existing Java types. In `nl2br(text)`, strip characters outside the XML 1.0 character ranges before escaping and adding line breaks. Add the content-type declaration used by Wunderland's `9555cb2` to the shared head.
- [x] Run the smoke suite. In a built image, check the four installer types through nginx and parse the rendered page for bundled game 3820. Commit the compatibility changes.

## Task 4 — Handle slashes, negative pages, and missing vendors

**Files** — `dedo/blueprints/store.py`, `dedo/templates/vendors.html`, `tests/smoke_test.py`.

- [x] Add tests that follow the rendered vendor link for `Hugo Games A/S`, search for `A/B` through the form, and navigate page 2 for slash-containing input. Assert that a negative page redirects to the first page and that an unknown vendor returns the XHTML 404. Check legacy first-page and paginated URLs in the same run.
- [x] Support slash-containing search and vendor values at the web routing boundary. Keep the existing path forms for ordinary values. For values containing a slash, use `GET /games/search?q=<query>&page=<n>` and `GET /games/vendor?name=<vendor>&page=<n>` so values ending in `/page/<n>` stay unambiguous. Make the form, vendor links, and pagination links use the same representation. Accept signed page numbers so the existing pagination helper can redirect negative values. Return 404 for an unknown named vendor.
- [x] Run the smoke suite and verify that ordinary existing URLs, `/page/0`, past-the-end redirects, and the bundled vendor link all behave as asserted. Commit the routing changes.

## Task 5 — Make database upgrades explicit and validate Mongo ports

**Files** — `dedo/config.py`, `README.md`, `tests/smoke_test.py`.

- [x] Add startup checks that expect a helpful `ConfigError` for a YAML file containing `mongodb_uri`, including a check that the diagnostic omits its value. Assert that `MONGO_PORT=0`, `65536`, and `²` fail with a message naming `MONGO_PORT`, while an omitted port defaults to 27017.
- [x] Reject the obsolete key in `_validate(data)`. Require an ASCII decimal port in the range 1–65535 whenever the environment specifies a nonempty value. Keep credential quoting and the existing validation summary.
- [x] Update the upgrade guide to identify the live database from the old app's URI and reconcile it with the old Compose values before dumping, moving configuration, or starting the replacement. Explain that the bundled restore maps its own namespace and that an operator archive retains its namespace unless explicitly remapped.
- [x] Run the startup checks and rehearse the documented upgrade on a throwaway stack where the old URI names a database different from the initialization default. Verify the new app serves the operator catalogue. Commit the config and migration documentation.

## Task 6 — Fix Compose readiness and index-job instructions

**Files** — `compose.yaml`, `README.md`.

- [x] Record two failures in a disposable project. An initialized database with zero games fails the current probe despite a successful ping, and `docker compose up -d --build --wait` exits when the index job completes successfully. Confirm the standalone index command needs the app image.
- [x] Change the db health command to an authenticated ping over the Docker network via `--host db`. This keeps the loopback-only initialization server out of the readiness check. Keep the one-shot index job and make successful completion a declared startup dependency of the app, so Compose can distinguish job completion from service failure. Verify that a failed index job blocks startup and that its duplicate-ID diagnostic is visible in the job logs. Document `docker compose build app` before standalone index maintenance on a fresh checkout, and explain that Compose selects the runtime UID/GID in `.env`.
- [x] Run `docker compose config --quiet`, then `docker compose up -d --build --wait` on a disposable stack with a custom database name. Verify the bundled 8,468 games were restored, `indexes` exited 0, and all long-running services are healthy. Verify startup again on an initialized empty catalogue and run the documented standalone index command. Commit the deployment changes.

## Task 7 — Record frozen behavior and close the verification gaps

**Files** — `tests/smoke_test.py`, `dedo/templates/`, this plan.

- [x] Add coverage for both paginated vendor routes, a bare missing-file 404, and `/healthz` returning 503 when Mongo ping fails. Check that the regex metacharacter test distinguishes literal search from matching everything and that the long-input test contains more than 100 non-whitespace characters.
- [x] Compare the baseline and current legacy API on the same fixtures. Record the observed `.*` search count change from 2 to 0, vendor ordering and pagination differences, and changed error bodies. Also record the branded indexing-enabled `/robots.txt` 404. Keep these as explicit compatibility decisions for the deferred work. In particular, do not reintroduce unchecked regex handling to recover the earlier API matching semantics.
- [x] Remove the ten trailing-whitespace lines reported in the extracted templates. Keep the historical finding about the `208dfea6` startup failure and its fix in `782750c3` in the review record.
- [x] Run `git diff --check`, dependency and syntax checks, and the complete smoke suite with the default config and with `per_page: 1`, a custom API prefix, and indexing toggled. In the disposable Compose stack, confirm nginx gzip, static cache headers, and a responsive storefront during a throttled download. Record the outcomes and commit the verification changes.

## Compatibility record (Task 7)

The baseline is the pre-refactor API at `3bc39d17`, run from a throwaway `git archive` checkout with its own `app/config.yml`. Both apps used the same two fixtures (`Smoke Game`, 5 downloads; `Other Game`, 50 downloads) and the same `per_page` values. The probes dropped their throwaway databases afterwards.

| Surface | Baseline (`3bc39d17`) | Current | Decision |
| --- | --- | --- | --- |
| `GET /api/v1/search/?q=.*&page=1` | `count: 2`, both fixtures; the query was compiled as a regex | `count: 0`, empty results; `.*` is literal text | Keep literal search. Do not reintroduce unchecked regex handling to recover the earlier matching semantics. |
| `GET /api/v1/vendors/?page=1` with `per_page: 1` | `list(set(...))` order varied between processes (`PYTHONHASHSEED` 1/2/4 put `Other Vendor` first; 3/5 put `Smoke Vendor` first), so page 1 and page 2 swapped | Sorted alphabetically: page 1 `Other Vendor`, page 2 `Smoke Vendor`; empty vendors are filtered out | Keep the deterministic sorted order. The legacy field names and response shape are unchanged, and the storefront and API now agree. |
| Error bodies | Parameter errors returned `{"error": "Invalid page"}` with 200; past-the-end API pages raised `BuildError` and returned Werkzeug's HTML 500; `/robots.txt` with indexing enabled returned Werkzeug's HTML 404 | Parameter errors are unchanged; the unhandled 500 is Dedo's XHTML “Server error” page; web 404s are Dedo's XHTML “Not found” page; a missing content file is a bare 404 without that page | Keep the branded XHTML shell for web errors and the bare file 404. JSON API error and pagination cleanup remains deferred; the unhandled past-the-end `BuildError` is unchanged from the baseline. |
| `GET /robots.txt` with `allow_indexing: true` | 404, Werkzeug HTML | 404, branded Dedo XHTML “Not found” | Do not add a generated robots file now. The SEO work is deferred; with indexing disabled the existing disallow-all file is still served. |

Unknown vendor routing keeps both behaviours: `/games/vendor/<name>` still redirects to `/games/vendors`, while `/games/vendor?name=<name>` returns the XHTML 404. The plan freezes the existing path forms and only introduces the named query form for slash values, so the smoke suite now asserts both outcomes.

Superseded by [the SEO plan](2026-11-25-dedo-seo.md), Task 5: both vendor forms now return the XHTML 404, and `/` redirects permanently (301).

## Verification record (Task 7)

- `git diff --check`: clean.
- `.venv/bin/pip check`: `No broken requirements found.`
- `.venv/bin/python -m compileall -q dedo tests`: clean. `.venv/bin/python -m pyflakes dedo tests`: no output.
- Smoke suite, 66/66 checks each, on the tracked `config.yaml.example` (indexing enabled) and on three variants: `per_page: 1`, `api_prefix: '/api/custom'`, and `allow_indexing: false`. The local `config.yaml` still carries the obsolete `mongodb_uri`, which Task 5 rejects; the runs used `DEDO_CONFIG` with the example settings and throwaway databases.
- The `per_page: 1` run exposed a hard-coded vendor page in the smoke suite (`/api/v1/vendors/?page=1` assumed `Other Vendor` was on page 1). The check now computes the page from the sorted vendor list, which keeps the default and small-page configurations green.
- Disposable Compose project `dedo-task7-redo` with `MONGO_DB=dedo_task7_redo_compose`: `docker compose config --quiet` passed; `up -d --build --wait` brought `app`, `db` and `proxy` up healthy with `indexes` exited 0; the restored catalogue held 8,468 games.
- Through the nginx proxy: `/healthz` returned `ok`; `/static/css/style.css` returned `Content-Encoding: gzip`, `Vary: Accept-Encoding` and `Cache-Control: public, max-age=86400`; `/games` also returned gzip. While a 20 MB file was downloaded through the proxy at 10 kB/s, three `/games` requests returned 200 in 0.0063 s, 0.0062 s and 0.0153 s. The project was removed with `down -v` afterwards.
- Built image through nginx: the four fixture downloads returned `application/vnd.symbian.install` (`.sis`), `x-epoc/x-sisx-app` (`.sisx`), `application/java-archive` (`.jar`) and `text/vnd.sun.j2me.app-descriptor; charset=utf-8` (`.jad`). Bundled games 3820 and 4 returned 200 and parsed as XML; game 4 rendered both splash and screenshot links. `/games/top` returned 200 in 0.035 s through the proxy, with *Real Football 2018* first.
- Empty catalogue: a fresh project with the import directory replaced by an empty directory (`MONGO_DB=dedo_task7_empty`) started `db`, `app` and `proxy` healthy, `indexes` exited 0, the games count was 0 and `/healthz` returned `ok`.
- Failed index job: after seeding two games with id 7, `up -d --wait` exited 1, `indexes` exited 1, `app` and `proxy` were not started, and the job log contained `Cannot create the unique id index; duplicate game ids: [7]`.
- The documented standalone command `docker compose run --rm indexes` printed `Created indexes: id_unique, vendor, downloads_desc, banner`.
