import os

import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(ROOT_DIR, "config.yaml")

with open(path, "r") as f:
    config = yaml.safe_load(f.read())
