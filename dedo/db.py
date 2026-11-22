import re

import pymongo
from pymongo.errors import DuplicateKeyError

from .cache import ttl_cache
from .config import MONGO_DB, MONGO_URI, config

# Only these fields may be used as a sort key; the value is the stored name.
SORT_FIELDS = {"downloads": "downloads", "id": "id"}

client = pymongo.MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=4000,
    connectTimeoutMS=4000,
)


def get_collection(collection_name):
    return client[MONGO_DB].get_collection(collection_name)


def _title_regex(query):
    """Escape the user's text so it searches literally, or None when empty."""
    query = (query or '').strip()[:100]
    if not query:
        return None
    return re.compile(re.escape(query), re.IGNORECASE)


def _game_conditions(conditions=None, resolution=None):
    conditions = dict(conditions or {})
    if resolution:
        conditions[f'resolutions.{resolution}'] = {'$exists': True}
    return conditions


def ping():
    # Leave time for /healthz to respond before Compose's four-second HTTP timeout.
    with pymongo.timeout(3):
        client.admin.command("ping")


def create_indexes():
    games_collection = get_collection('games')
    try:
        return [
            games_collection.create_index([("id", 1)], unique=True, name="id_unique"),
            games_collection.create_index([("vendor", 1)], name="vendor"),
            games_collection.create_index([("downloads", -1)], name="downloads_desc"),
            games_collection.create_index([("banner", 1)], name="banner"),
        ]
    except DuplicateKeyError as error:
        duplicates = games_collection.aggregate([
            {'$group': {'_id': '$id', 'count': {'$sum': 1}}},
            {'$match': {'count': {'$gt': 1}}},
            {'$sort': {'_id': 1}},
        ])
        ids = [document['_id'] for document in duplicates]
        raise RuntimeError(
            f"Cannot create the unique id index; duplicate game ids: {ids}"
        ) from error


def count_games(conditions=None, resolution=None, limit=None):
    conditions = _game_conditions(conditions, resolution)
    total = get_collection('games').count_documents(conditions)
    if limit is not None:
        total = min(total, limit)
    return total


def count_search(query):
    regex = _title_regex(query)
    if regex is None:
        return 0
    return get_collection('games').count_documents({'title': regex})


def search(query, page=None, return_total=False):

    regex = _title_regex(query)
    if regex is None:
        return ([], 0) if return_total else []

    games_collection = get_collection('games')
    conditions = {'title': regex}
    projection = {'resolutions': 0, '_id': 0}

    cursor = games_collection.find(conditions, projection)

    if page is not None:
        skip = (page - 1) * config['per_page']
        cursor = cursor.skip(skip).limit(config['per_page'])

    results = cursor.to_list()
    results = [{**result, 'date': result['date'].strftime("%d.%m.%Y")} for result in results]

    if return_total:
        return results, count_search(query)

    return results

def get_random_game(banner=None):

    games_collection = get_collection('games')
    pipeline = []

    if banner is not None:
        pipeline.append({'$match': {'banner': banner}})

    pipeline.append({'$sample': {'size': 1}})
    pipeline.append({'$unset': ['_id']})

    cursor = games_collection.aggregate(pipeline)
    try:
        return next(cursor)
    except StopIteration:
        return None

def get_games(conditions=None, sort=None, limit=None, resolution=None, full_results=False, page=None, return_count=False):

    conditions = _game_conditions(conditions, resolution)

    games_collection = get_collection('games')

    projection = {'_id': 0}

    if not full_results:
        projection['resolutions'] = 0

    cursor = games_collection.find(conditions, projection)

    if sort is not None:
        if sort not in SORT_FIELDS:
            raise ValueError(f"Unsupported sort: {sort}")
        cursor = cursor.sort(SORT_FIELDS[sort], -1)

    query_limit = limit
    if page is not None:
        per_page = config['per_page']
        skip = (page - 1) * per_page
        cursor = cursor.skip(skip)
        query_limit = per_page if limit is None else min(per_page, limit - skip)

    # MongoDB treats a limit of zero as unlimited.
    if page is not None and query_limit <= 0:
        results = []
    else:
        if query_limit is not None:
            cursor = cursor.limit(query_limit)
        results = cursor.to_list()

    if return_count:
        return results, count_games(conditions, limit=limit)

    return results

def get_game(id):
    games_collection = get_collection('games')

    result = games_collection.find_one({'id': id}, {'_id': 0})
    if not result:
        return None
    result['date'] = result['date'].strftime('%d.%m.%Y')
    return result

# Derived from the games collection, which can gain rows between restarts:
# a short TTL instead of Wunderland's cache-until-restart. See spec D6.
@ttl_cache(300)
def get_vendors():
    vendors = client[MONGO_DB].games.distinct("vendor")
    return sorted(vendor for vendor in vendors if vendor)

@ttl_cache(300)
def get_resolutions():
    games_collection = get_collection('games')

    # Use aggregation to extract resolution keys server-side for better performance
    # Pipeline: convert resolutions object to array, unwind, collect unique keys
    pipeline = [
        {'$project': {'resArray': {'$objectToArray': '$resolutions'}}},
        {'$unwind': {'path': '$resArray'}},
        {'$group': {'_id': None, 'keys': {'$addToSet': '$resArray.k'}}},
        {'$project': {'_id': 0, 'keys': 1}}
    ]

    cursor = games_collection.aggregate(pipeline)
    try:
        doc = next(cursor)
        keys = doc.get('keys', [])
    except StopIteration:
        keys = []

    return sorted(keys)
