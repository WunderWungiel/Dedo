import os
import math
from datetime import datetime

from flask import Flask, redirect, render_template, url_for, send_from_directory, request
import humanize

from lib import config, db
from lib import api_blueprint

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config['SECRET_KEY'] = config['secret_key']

if config['proxy']:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

app.register_blueprint(api_blueprint)

def generate_pages(page, total_pages):
    return {
        'current': page,
        'next': page + 1 if page < total_pages else None,
        'previous': page - 1 if page > 1 else None,
        'first': 1,
        'last': total_pages,
        'total': total_pages
    }

@app.context_processor
def utility_processor():
    return dict(
        now=datetime.now()
    )

@app.route("/")
def root():
    return redirect(url_for('games'))

@app.route("/games")
def games():
    
    random_game = db.get_random_game(banner=True)

    return render_template("index.html", random_game=random_game)

@app.route("/games/<int:id>/screens")
def game_resolutions(id):

    game = db.get_game(id)

    return render_template("resolutions.html", game=game)

@app.route("/games/<int:id>")
@app.route("/games/<int:id>/screen/<resolution>")
def game_resolution(id, resolution=None):
    
    game = db.get_game(id)

    resolutions_to_use = [resolution] if resolution else game['resolutions'].keys()

    for temp_resolution in resolutions_to_use:
        for model, files in game['resolutions'][temp_resolution].items():
            for i, file in enumerate(files):
                if not file.get('filename'):
                    size = 0
                else:
                    path = os.path.join("static", "content", "files", file['filename'])
                    size = os.path.getsize(path) if os.path.isfile(path) else 0
                game['resolutions'][temp_resolution][model][i]['size'] = humanize.naturalsize(size)

    return render_template("game.html", game=game, resolution=resolution)

@app.route("/games/search", methods=['GET', 'POST'])
def search():

    if request.method == 'GET':
        return render_template("search.html", text=request.args.get('text'))
    
    elif request.method == 'POST':

        query = request.form.get('q')

        if not query:
            return redirect(url_for('root'))

        return redirect(url_for('search_query', query=query, page=1))

@app.route("/games/search/<query>")
@app.route("/games/search/<query>/page/<int:page>")
def search_query(query, page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint, query=query))
    
    results, total = db.search(query, page=page, return_total=True)

    if not total:
        return redirect(url_for('search', text="No matches found!"))

    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint, query=query))

    pages = generate_pages(page, total_pages)

    return render_template("search_results.html", results=results, query=query, pages=pages)

@app.route("/games/top")
@app.route("/games/top/page/<int:page>")
def top_games(page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint))

    results, total = db.get_games(sort='downloads', limit=50, page=page, return_count=True)

    if not total:
        return redirect(url_for('root'))
    
    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint))

    pages = generate_pages(page, total_pages)
    
    return render_template("list.html", endpoint=request.endpoint, results=results, text="TOP 50 games", pages=pages)

@app.route("/games/latest")
def latest_games():

    results = db.get_games(sort='id', limit=15)

    pages = generate_pages(page=1, total_pages=1)

    return render_template("list.html", endpoint=request.endpoint, results=results, text="Latest games", pages=pages)

@app.route("/games/vendors")
@app.route("/games/vendors/page/<int:page>")
def vendors(page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint))
    
    results = db.get_vendors()
    total = len(results)

    if not total:
        return redirect(url_for('root'))
    
    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint))
    
    first_index = (page - 1) * config['per_page']
    last_index = first_index + config['per_page']

    paged_results = results[first_index:last_index]
    pages = generate_pages(page, total_pages)
    
    return render_template("vendors.html", results=paged_results, text="Latest games", pages=pages)

@app.route("/games/vendor/<vendor>")
@app.route("/games/vendor/<vendor>/page/<int:page>")
def vendor_games(vendor, page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint, vendor=vendor))

    results, total = db.get_games(conditions={'vendor': vendor}, page=page, return_count=True)

    if not total:
        return redirect(url_for('vendors'))
    
    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint, vendor=vendor))

    pages = generate_pages(page, total_pages)

    return render_template("list.html", endpoint=request.endpoint, results=results, text=vendor, url_args={'vendor': vendor}, pages=pages)

@app.route("/games/screens")
def games_resolutions():

    resolutions = db.get_resolutions()

    return render_template("resolutions_list.html", resolutions=resolutions)

@app.route("/games/screen/<resolution>")
@app.route("/games/screen/<resolution>/page/<int:page>")
def resolution_games(resolution, page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint, resolution=resolution))

    results, total = db.get_games(resolution=resolution, page=page, return_count=True)

    if not total:
        return redirect(url_for('games_resolutions'))
    
    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint, resolution=resolution))

    pages = generate_pages(page, total_pages)
    
    return render_template("list.html", endpoint=request.endpoint, results=results, text=f"{resolution} games", url_args={'resolution': resolution}, pages=pages)

@app.route("/games/browse")
@app.route("/games/browse/page/<int:page>")
def browse_games(page=None):

    page = page or 1

    if page < 1:
        return redirect(url_for(request.endpoint))

    results, total = db.get_games(page=page, return_count=True)

    if not total:
        return redirect(url_for('root'))
    
    total_pages = max(1, math.ceil(total / config['per_page']))

    if page > total_pages:
        return redirect(url_for(request.endpoint))

    pages = generate_pages(page, total_pages)
    
    return render_template("list.html", endpoint=request.endpoint, results=results, text="All games", pages=pages)

if not config['allow_indexing']:
    @app.route("/robots.txt")
    def robots():
        return send_from_directory(app.static_folder, "robots.txt")

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
