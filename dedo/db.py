import re

import pymongo

from .config import config
client = pymongo.MongoClient(config['mongodb_uri'])

def get_collection(collection_name):
    db = client.get_default_database()
    return db.get_collection(collection_name)

def search(query, page=None, return_total=False):

    regex = re.compile(query, re.IGNORECASE)

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
        total = games_collection.count_documents(conditions)
        return results, total

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

    conditions = conditions or {}

    if resolution:
        conditions[f'resolutions.{resolution}'] = {'$exists': True}

    games_collection = get_collection('games')
    
    projection = {'_id': 0}

    if not full_results:
        projection['resolutions'] = 0

    cursor = games_collection.find(conditions, projection)

    if sort is not None:
        cursor = cursor.sort(sort, -1)

    if limit is not None:
        cursor = cursor.limit(limit)

    if page is not None:
        skip = (page - 1) * config['per_page']
        cursor = cursor.skip(skip).limit(config['per_page'])

    results = cursor.to_list()

    if return_count:

        total = games_collection.count_documents(conditions)

        if limit is not None:
            total = min(total, limit)

        return results, total

    return results

def get_game(id):
    games_collection = get_collection('games')

    result = games_collection.find_one({'id': id}, {'_id': 0})
    if not result:
        return None
    result['date'] = result['date'].strftime('%d.%m.%Y')
    return result

def get_vendors():

    games_collection = get_collection('games')
    cursor = games_collection.find({}, {'_id': 0, 'vendor': 1})
    results = cursor.to_list()

    vendors = [result['vendor'] for result in results]

    return list(set(vendors))

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
