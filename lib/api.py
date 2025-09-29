import math
import os

from flask import Blueprint, request, redirect, url_for, current_app

from . import config, db, utils

api = Blueprint("api", __name__, template_folder="templates", url_prefix=config["api_prefix"])

def generate_error(content):
    return {
        "error": content
    }

@api.route("/resolution/")
def _resolution():
    page = request.args.get("page")
    if not page or not page.isnumeric() or int(page) < 1:
        return generate_error("Invalid page")
    page = int(page)

    resolution = request.args.get("name")
    if not resolution:
        return generate_error("Missing parameter: name")
    
    body = {}

    results = list(db.get_games(resolution=resolution))

    if len(results) == 0:
        body["results"] = []
        body["total_pages"] = 0
        body["count"] = 0
        return body

    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for("._resolution", page=1))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]
    body["results"] = list(paged_results)
    body["total_pages"] = total_pages
    body["count"] = len(results)

    return body

@api.route("/resolutions/")
def _resolutions():
    return db.get_resolutions()

@api.route("/vendor/")
def _vendor():
    page = request.args.get("page")
    if not page or not page.isnumeric() or int(page) < 1:
        return generate_error("Invalid page")
    page = int(page)

    vendor = request.args.get("name")
    if not vendor:
        return generate_error("Missing parameter: name")
    
    body = {}

    results = list(db.get_games({"vendor": vendor}))

    if len(results) == 0:
        body["results"] = []
        body["total_pages"] = 0
        body["count"] = 0
        return body

    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for("._vendor", page=1))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]
    body["results"] = list(paged_results)
    body["total_pages"] = total_pages
    body["count"] = len(results)

    return body

@api.route("/vendors/")
def _vendors():
    page = request.args.get("page")
    if not page or not page.isnumeric() or int(page) < 1:
        return generate_error("Invalid page")
    page = int(page)

    body = {}

    results = db.get_vendors()

    if len(results) == 0:
        body["results"] = []
        body["total_pages"] = 0
        body["count"] = 0
        return body

    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for("._vendors", page=1))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]
    body["results"] = list(paged_results)
    body["total_pages"] = total_pages
    body["count"] = len(results)

    return body

@api.route("/game/")
def _game():
    
    id = request.args.get("id")
    if not id or not id.isnumeric():
        return generate_error("Invalid parameter: id")
    id = int(id)

    resolution = request.args.get("resolution")
    if not resolution:
        return generate_error("Missing parameter: resolution")

    game = db.get_game(id)
    if resolution not in game["resolutions"]:
        return generate_error("Invalid resolution")
    
    game["links"] = game["resolutions"][resolution]

    for model, files in game["links"].items():
        for i, file in enumerate(files):
            if not file.get('filename'):
                size = 0
            else:
                path = os.path.join(current_app.static_folder, "files", file['filename'])
                size = os.path.getsize(path) if os.path.isfile(path) else 0
            game["links"][model][i]['size'] = utils.format_size(size)

    return game if game else generate_error("Non-existent parameter: id")

@api.route("/game/resolutions/")
def _game_resolutions():
    id = request.args.get("id")
    if not id or not id.isnumeric():
        return generate_error("Invalid parameter: id")
    id = int(id)

    game = db.get_game(id)
    return list(game["resolutions"]) if game and game.get("resolutions") else []

@api.route("/search/")
def _search():

    query = request.args.get("q")
    if not query:
        return generate_error("Missing parameter: q")
    
    page = request.args.get("page")
    if not page or not page.isnumeric() or int(page) < 1:
        return generate_error("Invalid page")
    page = int(page)
    
    body = {}

    results = db.search(query)
    if len(results) == 0:
        body["results"] = []
        body["total_pages"] = 0
        body["count"] = 0
        return body

    total_pages = math.ceil(len(results) / config["per_page"])

    if page > total_pages:
        return redirect(url_for("._search", q=query, page=1))
    
    paged_results = results[(page - 1) * config["per_page"] : page * config["per_page"]]
    body["results"] = list(paged_results)
    body["total_pages"] = total_pages
    body["count"] = len(results)

    return body

