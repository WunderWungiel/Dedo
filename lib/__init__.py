import pymongo

from .config import config

client = pymongo.MongoClient(config["mongodb_uri"])
