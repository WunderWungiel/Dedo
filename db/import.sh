#!/bin/sh

mongorestore --stopOnError --nsInclude='dedomil.*' \
    --nsFrom='dedomil.*' --nsTo="${MONGO_INITDB_DATABASE}.*" \
    /docker-entrypoint-initdb.d/dump
