import atexit
from datetime import datetime

from flask import Flask, render_template, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import CONTENT_DIR, config
from . import cli, db, helpers
from .blueprints.api import api as api_blueprint
from .blueprints.store import store as store_blueprint

atexit.register(db.client.close)

# Endpoints that serve files, where a missing file is a plain 404, not a page.
FILE_ENDPOINTS = {'static', 'content'}

app = Flask(__name__)
app.url_map.strict_slashes = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 86400
app.wsgi_app = ProxyFix(
    app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)

app.register_blueprint(api_blueprint)
app.register_blueprint(store_blueprint)
app.cli.add_command(cli.create_indexes)


@app.context_processor
def utility_processor():
    return dict(
        now=datetime.now()
    )


@app.template_filter('nl2br')
def nl2br_filter(text):
    return helpers.nl2br(text)


@app.route("/static/content/<path:filename>")
def content(filename):
    return send_from_directory(CONTENT_DIR, filename)


@app.errorhandler(404)
def not_found(e):
    if request.endpoint in FILE_ENDPOINTS:
        return e
    return render_template(
        "error.html",
        title="Not found",
        message="The page you asked for does not exist.",
        show_navigation=True
    ), 404


@app.errorhandler(500)
def server_error(e):
    if request.endpoint in FILE_ENDPOINTS:
        return e
    return render_template(
        "error.html",
        title="Server error",
        message="Something went wrong. Please try again later.",
        show_navigation=False
    ), 500


if not config['allow_indexing']:
    @app.route("/robots.txt")
    def robots():
        return send_from_directory(app.static_folder, "robots.txt")

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=8000)
