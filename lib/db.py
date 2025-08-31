import re
from datetime import datetime

from . import client

def get_collection(collection_name):
    db = client.get_default_database()
    return db.get_collection(collection_name)

def search(query):
    games_collection = get_collection("games")

    regex = re.compile(query, re.IGNORECASE)

    results = games_collection.find({ "title": regex }, {"resolutions": 0}).to_list()
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

def get_games(conditions=None, resolution=None, full_results=False):

    conditions = conditions or {}
    if resolution:
        conditions[f"resolutions.{resolution}"] = {"$exists": True}

    games_collection = get_collection("games")

    return games_collection.find(conditions, {} if full_results else {"resolutions": 0}).to_list()

def get_game(id):
    games_collection = get_collection("games")

    result = games_collection.find_one({ "id": id })
    result['date'] = result['date'].strftime('%d.%m.%Y')
    return result

def get_top_games(limit=50):
    games_collection = get_collection("games")

    results = games_collection.find({}, {"resolutions": 0}).sort("downloads", -1).limit(limit).to_list()
    return results

def get_latest_games(limit=15):
    games_collection = get_collection("games")

    results = games_collection.find({}, {"resolutions": 0}).sort("id", -1).limit(limit).to_list()
    return results

def get_vendors():
    games_collection = get_collection("games")

    results = games_collection.find({}, {"_id": 0, "vendor": 1}).to_list()

    vendors = [result["vendor"] for result in results]
    return list(set(vendors))

def get_resolutions():
    games_collection = get_collection("games")
    results = games_collection.find({}, {"_id": 0, "resolutions": 1})

    resolutions = list({key for result in results for key in result["resolutions"].keys()}) # Curly brackets make set - removing duplicates
    return resolutions

def get_games_by_model(model_query):

    results = []

    games = get_games(full_results=True)
    for game in games:
        found = False
        for resolution in game['resolutions']:
            for model in game['resolutions'][resolution].keys():
                if model_query.lower() in model.lower():
                    found = True
                    break
            if found:
                break
        if found:
            results.append(game)

    return results
