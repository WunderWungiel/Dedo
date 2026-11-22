from flask import Blueprint, abort, redirect, render_template, request, url_for

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
    return redirect(url_for('store.games'))


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
        return render_template("search.html", text=request.args.get('text'))

    query = request.form.get('q')

    if not query:
        return redirect(url_for('store.root'))

    return redirect(url_for('store.search_query', query=query, page=1))


@store.route("/games/search/<query>")
@store.route("/games/search/<query>/page/<int:page>")
def search_query(query, page=None):

    page = page if page is not None else 1
    total = db.count_search(query)

    if not total:
        return redirect(url_for('store.search', text="No matches found!"))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.search(query, page=page),
        request.endpoint, config['per_page'], {'query': query})
    if redirect_response:
        return redirect_response

    return render_template("search_results.html", results=results, query=query, pages=pages)


@store.route("/games/top")
@store.route("/games/top/page/<int:page>")
def top_games(page=None):

    page = page if page is not None else 1
    total = db.count_games(limit=50)

    if not total:
        return redirect(url_for('store.root'))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(sort='downloads', limit=50, page=page),
        request.endpoint, config['per_page'])
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text="TOP 50 games", pages=pages)


@store.route("/games/latest")
def latest_games():

    results = db.get_games(sort='id', limit=15)

    pages = helpers.generate_pages(page=1, total_pages=1)

    return render_template("list.html", endpoint=request.endpoint, results=results, text="Latest games", pages=pages)


@store.route("/games/vendors")
@store.route("/games/vendors/page/<int:page>")
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
@store.route("/games/vendor/<vendor>/page/<int:page>")
def vendor_games(vendor, page=None):

    page = page if page is not None else 1
    total = db.count_games(conditions={'vendor': vendor})

    if not total:
        return redirect(url_for('store.vendors'))

    results, pages, redirect_response = helpers.paginate(
        page, total, lambda page: db.get_games(conditions={'vendor': vendor}, page=page),
        request.endpoint, config['per_page'], {'vendor': vendor})
    if redirect_response:
        return redirect_response

    return render_template("list.html", endpoint=request.endpoint, results=results, text=vendor, url_args={'vendor': vendor}, pages=pages)


@store.route("/games/screens")
def games_resolutions():

    resolutions = db.get_resolutions()

    return render_template("resolutions_list.html", resolutions=resolutions)


@store.route("/games/screen/<resolution>")
@store.route("/games/screen/<resolution>/page/<int:page>")
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

    return render_template("list.html", endpoint=request.endpoint, results=results, text=f"{resolution} games", url_args={'resolution': resolution}, pages=pages)


@store.route("/games/browse")
@store.route("/games/browse/page/<int:page>")
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

    return render_template("list.html", endpoint=request.endpoint, results=results, text="All games", pages=pages)
