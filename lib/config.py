import os

import yaml

path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "config.yml")

with open(path, "r") as f:
    config = yaml.safe_load(f.read())
