import math
import os

import humanize
from flask import redirect, url_for
from markupsafe import Markup, escape

from .config import CONTENT_DIR


def generate_pages(page, total_pages):
    return {
        'current': page,
        'next': page + 1 if page < total_pages else None,
        'previous': page - 1 if page > 1 else None,
        'first': 1,
        'last': total_pages,
        'total': total_pages
    }


def page_redirect(endpoint, page, url_args=None):
    args = dict(url_args or {})
    # Page 1 has no /page/1 in its URL, so only add the argument beyond it.
    if page > 1:
        args['page'] = page
    return redirect(url_for(endpoint, **args))


def paginate(page, total, fetch, endpoint, per_page, url_args=None):
    total_pages = max(1, math.ceil(total / per_page))

    if page < 1:
        return None, None, page_redirect(endpoint, 1, url_args)

    if page > total_pages:
        return None, None, page_redirect(endpoint, total_pages, url_args)

    return fetch(page), generate_pages(page, total_pages), None


def get_content_path(filename):
    return os.path.join(CONTENT_DIR, "files", filename)


def file_size(filename):
    if not filename:
        return 0
    path = get_content_path(filename)
    return os.path.getsize(path) if os.path.isfile(path) else 0


def attach_file_sizes(game, resolution=None):
    resolutions = game["resolutions"]
    selected = resolutions.values() if resolution is None else (resolutions[resolution],)
    for models in selected:
        for files in models.values():
            for file in files:
                file["size"] = humanize.naturalsize(file_size(file.get("filename")))
    return game


def nl2br(text):
    if text is None:
        return Markup("")
    return Markup("<br/>").join(escape(text).split("\n"))
