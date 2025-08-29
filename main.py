import os
import math

from flask import Flask, redirect, render_template, url_for, request

from lib import config, db

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config['secret_key'] = config["secret_key"]

if config["proxy"]:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )

def format_size(size_bytes, decimals=2):

    if size_bytes == 0:
        return "0 bytes"
    
    power = 1024
    units = ["bytes", "KB", "MB", "GB", "TB", "PB"]

    i = int(math.floor(math.log(size_bytes, power)))
    return f"{size_bytes / (power ** i):.{decimals}f} {units[i]}"

def paginate(results, page, base_url, template, extra_content=None, url_args=None):

    if not page or page < 1:
        return redirect(url_for(base_url, page=1, **(url_args or {})))
    
    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for(base_url, page=1, **(url_args or {})))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]

    context = {
        "results": paged_results,
        "page": page,
        "total_pages": total_pages,
        "url": url_for(base_url, **(url_args or {}))
    }

    if extra_content:
        context.update(extra_content)

    return render_template(template, **context)

@app.route("/")
def _root():
    return redirect(url_for("_games"))

@app.route("/games")
def _games():
    return render_template("index.html", random_game=db.get_random_game(banner=True))

@app.route("/games/<int:id>/screens")
def _game_resolutions(id):
    
    return render_template("resolutions.html", game=db.get_game(id))

@app.route("/games/<int:id>")
@app.route("/games/<int:id>/screen/<resolution>")
def _game_resolution(id, resolution=None):
    
    game = db.get_game(id)

    resolutions_to_use = [resolution] if resolution else game['resolutions'].keys()

    for temp_resolution in resolutions_to_use:
        for model, files in game['resolutions'][temp_resolution].items():
            for i, file in enumerate(files):
                if not file.get('filename'):
                    size = 0
                else:
                    path = os.path.join("static", "files", file['filename'])
                    size = os.path.getsize(path) if os.path.isfile(path) else 0
                game['resolutions'][temp_resolution][model][i]['size'] = format_size(size)

    return render_template("game.html", game=game, resolution=resolution)

@app.route("/games/search", methods=["GET", "POST"])
def _search():
    if request.method == "GET":
        return render_template("search.html", text=request.args.get("text"))
    elif request.method == "POST":
        if not request.form.get("q"):
            return redirect(url_for("_root"))

        return redirect(url_for("_search_query", query=request.form.get("q"), page=1))

@app.route("/games/search/<query>/page/<int:page>")
def _search_query(query, page):

    if page < 1:
        return redirect(url_for("_search"))

    results = db.search(query)
    if len(results) == 0:
        return redirect(url_for("_search", text="No matches found!"))

    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for("_search"))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]

    return render_template("search_results.html", query=query, results=paged_results, page=page, total_pages=total_pages)

@app.route("/games/top")
@app.route("/games/top/page/<int:page>")
def _top_games(page=None):
    results = db.get_top_games(50)

    if len(results) == 0:
        return redirect(url_for("_root"))
    
    return paginate(results, page, "_top_games", "list.html", {"text": "TOP 50 games"})

@app.route("/games/latest")
def _latest_games():
    results = db.get_top_games(15)
    return render_template(
        "list.html",
        base_url="/games/latest",
        text="Latest games",
        results=results,
        page=1,
        total_pages=1
    )

@app.route("/games/vendors")
@app.route("/games/vendors/page/<int:page>")
def _vendors(page=None):
    results = db.get_vendors()

    if len(results) == 0:
        return redirect(url_for("_root"))
    
    return paginate(results, page, "_vendors", "vendors.html")

@app.route("/games/vendor/<vendor>")
@app.route("/games/vendor/<vendor>/page/<int:page>")
def _vendor_games(vendor, page=None):
    results = db.get_games({"vendor": vendor})

    if len(results) == 0:
        return redirect(url_for("_vendors"))

    return paginate(results, page, "_vendor_games", "list.html", extra_content={"text": vendor}, url_args={"vendor": vendor})

@app.route("/games/screens")
def _games_resolutions():
    return render_template("resolutions_list.html", resolutions=db.get_resolutions())

@app.route("/games/screen/<resolution>")
@app.route("/games/screen/<resolution>/page/<int:page>")
def _resolution_games(resolution, page=None):
    results = db.get_games(resolution=resolution)

    if len(results) == 0:
        return redirect(url_for("_games_resolutions"))
    
    return paginate(results, page, "_resolution_games", "list.html", extra_content={"text": f"{resolution} games"}, url_args={"resolution": resolution})

@app.route("/games/browse")
@app.route("/games/browse/page/<int:page>")
def _browse_games(page=None):
    results = db.get_games()

    if len(results) == 0:
        return redirect(url_for("_root"))
    
    return paginate(results, page, "_browse_games", "list.html", extra_content={"text": "All games"})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8080)
