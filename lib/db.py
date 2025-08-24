import re
from datetime import datetime

from . import client

def get_collection(collection_name):
    db = client.get_default_database()
    return db.get_collection(collection_name)

def search(query):
    games_collection = get_collection("games")

    regex = re.compile(query, re.IGNORECASE)

    results = games_collection.find({ "title": regex }).to_list()
    results = [{**result, "date": result["date"].strftime("%d.%m.%Y")} for result in results]
    return results

def get_random_game(banner=None):
    games_collection = get_collection("games")

    pipeline = []
    if banner is not None:
        pipeline.append({ "$match": { "banner": banner } })

    pipeline.append({ "$sample": { "size": 1 } })

    results = games_collection.aggregate(pipeline).to_list()
    return results[0] if len(results) > 0 else None

def get_games(id=None, title=None, vendor=None, resolution=None):

    query = {}
    if id:
        query["id"] = id
    if title:
        query["title"] = title
    if vendor:
        query["vendor"] = vendor
    if resolution:
        query[f"resolutions.{resolution}"] = {"$exists": True}

    games_collection = get_collection("games")

    return games_collection.find(query).to_list()

def get_game(id):
    games_collection = get_collection("games")

    result = games_collection.find_one({ "id": id })
    result['date'] = result['date'].strftime('%d.%m.%Y')
    return result

def get_top_games(limit=50):
    games_collection = get_collection("games")

    results = games_collection.find().sort("downloads", -1).limit(limit).to_list()
    return results

def get_latest_games(limit=15):
    games_collection = get_collection("games")

    results = games_collection.find().sort("id", -1).limit(limit).to_list()
    return results

def get_vendors():
    games_collection = get_collection("games")

    results = games_collection.find({}, {"_id": 0, "vendor": 1})

    return list(set([result["vendor"] for result in list(results)])) # Remove duplicates

def get_resolutions():
    games_collection = get_collection("games")
    results = games_collection.find({}, {"_id": 0, "resolutions": 1})

    resolutions = list({key for result in results for key in result["resolutions"].keys()})
    return resolutions
