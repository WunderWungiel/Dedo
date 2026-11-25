import math
import os
import re

import humanize
from flask import current_app, has_request_context, redirect, request, url_for
from markupsafe import Markup, escape

from .config import CANONICAL_URL, CONTENT_DIR

# XML 1.0 does not allow most control characters, and an escaped one still
# makes the page unparseable, so drop them before escaping.
XML_INVALID_CHARACTERS = re.compile(
    '[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]'
)


def canonical_url_for(endpoint, **values):
    """Build the absolute URL crawlers should use for an endpoint.

    Use it only for canonical links, og:url, og:image, the sitemap and robots.txt;
    page links stay on url_for. Without canonical_url it follows the request's scheme
    and host, so ProxyFix's forwarded values apply.
    """
    if CANONICAL_URL is None:
        return url_for(endpoint, _external=True, **values)
    adapter = current_app.url_map.bind(
        CANONICAL_URL.netloc, script_name=CANONICAL_URL.path or '/',
        url_scheme=CANONICAL_URL.scheme)
    return adapter.build(endpoint, values, force_external=True)


# The query args each listing reads to pick what it shows. Every other arg is left out
# of its canonical URL, so every variant of a listing points at one address.
CANONICAL_ARGS = {'store.vendor_games_query': ('name', 'page')}


def _positive_page(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 1 else None


def canonical_for_request():
    """The canonical URL of the current page, or None outside a matched route."""
    if not has_request_context() or request.url_rule is None:
        return None
    values = dict(request.view_args or {})
    if 'page' in values and not _positive_page(values['page']):
        del values['page']
    for name in CANONICAL_ARGS.get(request.endpoint, ()):
        if name == 'page':
            value = _positive_page(request.args.get('page', type=int))
        else:
            value = request.args.get(name) or None
        if value:
            values[name] = value
    return canonical_url_for(request.endpoint, **values)


SITE_DESCRIPTION = ('Free Java and Symbian games for classic mobile phones, '
                    'sorted by screen resolution.')
DESCRIPTION_LIMIT = 160


def meta_description(text, fallback=''):
    """Plain, single-line text for a description meta tag, at most 160 characters."""
    text = '' if text is None else str(text)
    text = ' '.join(XML_INVALID_CHARACTERS.sub('', text).split())
    if not text:
        return fallback
    if len(text) > DESCRIPTION_LIMIT:
        cut = text.rfind(' ', 0, DESCRIPTION_LIMIT - 3 + 1)
        text = text[:cut if cut > 0 else DESCRIPTION_LIMIT - 3].rstrip() + '...'
    return text


def og_image_for(game):
    """The canonical URL of a game's splash, else its screenshot, else None."""
    if not game:
        return None
    for field, folder in (('splash', 'splashes'), ('screenshot', 'screenshots')):
        filename = image_filename(game.get(field))
        if filename:
            return canonical_url_for('content', filename=f'images/{folder}/{filename}')
    return None


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


def image_filename(value: str | dict | None) -> str | None:
    """The trimmed stored filename for an image, whether it is a string or an object."""
    if isinstance(value, dict):
        value = value.get("filename")
    if isinstance(value, str):
        filename = value.strip()
        return filename or None
    return None


def date_dmy(value):
    """Render dates as dd.mm.yyyy, leaving already-formatted values alone."""
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d.%m.%Y")
    return value


def nl2br(text):
    if text is None:
        return Markup("")
    text = XML_INVALID_CHARACTERS.sub("", str(text))
    return Markup("<br/>").join(escape(text).split("\n"))
