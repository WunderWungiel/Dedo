import math
from xml.etree import ElementTree as ET

from flask import Blueprint, Response, abort, redirect, render_template, request, url_for

from .. import db, helpers
from ..config import config

store = Blueprint('store', __name__)


def _game_or_404(id):
    game = db.get_game(id)
    if game is None:
        abort(404)
    return game


@store.route("/")
def root():
    return redirect(url_for('store.games'), code=301)


@store.route("/games")
def games():

    random_game = db.get_random_game(banner=True)

    return render_template("index.html", random_game=random_game)


@store.route("/games/<int:id>/screens")
def game_resolutions(id):

    game = _game_or_404(id)

    return render_template("resolutions.html", game=game)


@store.route("/games/<int:id>")
@store.route("/games/<int:id>/screen/<resolution>")
def game_resolution(id, resolution=None):

    game = _game_or_404(id)

    if resolution is not None and resolution not in game['resolutions']:
        abort(404)

    helpers.attach_file_sizes(game, resolution=resolution)

    return render_template("game.html", game=game, resolution=resolution)


@store.route("/games/search", methods=['GET', 'POST'])
def search():

    if request.method == 'GET':
        query = request.args.get('q')
        if query:
            page = request.args.get('page', type=int)
            return _search_results(query, 1 if page is None else page,
                                   request.endpoint, {'q': query})
        return render_template("search.html", text=request.args.get('text'))

    query = request.form.get('q')

    if not query:
        return redirect(url_for('store.root'))

    # A slash cannot be a path segment, so those queries use the query form.
    if '/' in query:
        return redirect(url_for('store.search', q=query, page=1))

    return redirect(url_for('store.search_query', query=query, page=1))


def _search_results(query, page, endpoint, url_args):
    total = db.count_search(query)

    if not total:
        return redirect(url_for('store.search', text="No matches found!"))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda number: db.search(query, page=number),
        endpoint, config['per_page'], url_args)
    if redirect_response:
        return redirect_response

    return render_template("search_results.html", results=results, query=query,
                           endpoint=endpoint, url_args=url_args, pages=pages)


@store.route("/games/search/<query>")
@store.route("/games/search/<query>/page/<int(signed=True):page>")
def search_query(query, page=None):

    page = page if page is not None else 1
    return _search_results(query, page, request.endpoint, {'query': query})


@store.route("/games/top")
@store.route("/games/top/page/<int(signed=True):page>")
def top_games(page=None):

    page = page if page is not None else 1
    total = db.count_games(limit=50)

    if not total:
        return redirect(url_for('store.root'))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_top_games(page),
        request.endpoint, config['per_page'])
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text="TOP 50 games", description="The 50 most downloaded free mobile games.", pages=pages)


@store.route("/games/latest")
def latest_games():

    results = db.get_games(sort='id', limit=15)

    pages = helpers.generate_pages(page=1, total_pages=1)

    return render_template("list.html", endpoint=request.endpoint, results=results, text="Latest games", description="The 15 newest free mobile games.", pages=pages)


@store.route("/games/vendors")
@store.route("/games/vendors/page/<int(signed=True):page>")
def vendors(page=None):

    page = page if page is not None else 1
    results = db.get_vendors()
    total = len(results)

    if not total:
        return redirect(url_for('store.root'))

    per_page = config['per_page']

    def fetch(page_number):
        first_index = (page_number - 1) * per_page
        return results[first_index:first_index + per_page]

    paged_results, pages, redirect_response = helpers.paginate(
        page, total, fetch, request.endpoint, per_page)
    if redirect_response:
        return redirect_response

    return render_template("vendors.html", results=paged_results, text="Latest games", pages=pages)


@store.route("/games/vendor/<vendor>")
@store.route("/games/vendor/<vendor>/page/<int(signed=True):page>")
def vendor_games(vendor, page=None):

    page = page if page is not None else 1
    total = db.count_games(conditions={'vendor': vendor})

    if not total:
        abort(404)

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(conditions={'vendor': vendor}, page=page),
        request.endpoint, config['per_page'], {'vendor': vendor})
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text=vendor, title=f"Games by {vendor}", description=f"Free mobile games by {vendor}.", url_args={'vendor': vendor}, pages=pages)


@store.route("/games/vendor")
def vendor_games_query():
    """Vendor names containing a slash cannot be a single path segment."""

    vendor = request.args.get('name')

    if not vendor:
        return redirect(url_for('store.vendors'))

    page = request.args.get('page', type=int)
    page = 1 if page is None else page
    total = db.count_games(conditions={'vendor': vendor})

    if not total:
        abort(404)

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(conditions={'vendor': vendor}, page=page),
        request.endpoint, config['per_page'], {'name': vendor})
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text=vendor, title=f"Games by {vendor}", description=f"Free mobile games by {vendor}.", url_args={'name': vendor}, pages=pages)


@store.route("/games/screens")
def games_resolutions():

    resolutions = db.get_resolutions()

    return render_template("resolutions_list.html", resolutions=resolutions)


@store.route("/games/screen/<resolution>")
@store.route("/games/screen/<resolution>/page/<int(signed=True):page>")
def resolution_games(resolution, page=None):

    # The database lookup uses dot notation for resolution keys.
    if '.' in resolution:
        abort(404)

    page = page if page is not None else 1
    total = db.count_games(resolution=resolution)

    if not total:
        abort(404)

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(resolution=resolution, page=page),
        request.endpoint, config['per_page'], {'resolution': resolution})
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text=f"{resolution} games", description=f"Free mobile games for {resolution} screens.", url_args={'resolution': resolution}, pages=pages)


@store.route("/games/browse")
@store.route("/games/browse/page/<int(signed=True):page>")
def browse_games(page=None):

    page = page if page is not None else 1
    total = db.count_games()

    if not total:
        return redirect(url_for('store.root'))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(page=page),
        request.endpoint, config['per_page'])
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text="All games", description="Every free mobile game in the catalogue.", pages=pages)


SITEMAP_URLS_PER_FILE = 25000
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _sitemap_entries():
    """(absolute URL, lastmod) for every page worth indexing, in a stable order."""
    url = helpers.canonical_url_for
    entries = [(url(endpoint), None) for endpoint in (
        'store.games', 'store.top_games', 'store.latest_games',
        'store.browse_games', 'store.vendors', 'store.games_resolutions')]

    for vendor in db.get_vendors():
        if '/' in vendor:
            entries.append((url('store.vendor_games_query', name=vendor), None))
        else:
            entries.append((url('store.vendor_games', vendor=vendor), None))

    for resolution in db.get_resolutions():
        if '.' not in resolution and '/' not in resolution:
            entries.append((url('store.resolution_games', resolution=resolution), None))

    for game in db.get_sitemap_games():
        lastmod = game['date']
        entries.append((url('store.game_resolutions', id=game['id']), lastmod))
        entries.append((url('store.game_resolution', id=game['id']), lastmod))
        for resolution in game['resolutions']:
            if '/' not in resolution:
                entries.append((url('store.game_resolution', id=game['id'], resolution=resolution), lastmod))
    return entries


def _xml_response(root):
    ET.indent(root)
    body = ET.tostring(root, encoding='unicode', xml_declaration=False)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + body + '\n',
                    mimetype='application/xml')


@store.route("/sitemap.xml")
def sitemap():
    parts = math.ceil(len(_sitemap_entries()) / SITEMAP_URLS_PER_FILE)
    root = ET.Element('sitemapindex', xmlns=SITEMAP_NS)
    for part in range(1, parts + 1):
        ET.SubElement(ET.SubElement(root, 'sitemap'), 'loc').text = \
            helpers.canonical_url_for('store.sitemap_part', part=part)
    return _xml_response(root)


@store.route("/sitemap/<int:part>.xml")
def sitemap_part(part):
    entries = _sitemap_entries()
    start = (part - 1) * SITEMAP_URLS_PER_FILE
    if part < 1 or start >= len(entries):
        abort(404)
    root = ET.Element('urlset', xmlns=SITEMAP_NS)
    for loc, lastmod in entries[start:start + SITEMAP_URLS_PER_FILE]:
        element = ET.SubElement(root, 'url')
        ET.SubElement(element, 'loc').text = loc
        if lastmod is not None:
            ET.SubElement(element, 'lastmod').text = lastmod.strftime('%Y-%m-%d')
    return _xml_response(root)
