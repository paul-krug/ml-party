#!/bin/sh
# Initialize the store on first boot, then serve. Two auth modes:
#  - users configured (mlp user add against the /data volume, or an existing
#    auth/users.json in it): per-user login + tokens gate everything; any
#    ML_PARTY_TOKEN is ignored by mlp serve.
#  - no users: the legacy single ML_PARTY_TOKEN gates ingest.
# The container refuses to start with NEITHER — an unauthenticated tracking
# server is a foot-gun, not a mode.
set -e

if [ -z "${ML_PARTY_TOKEN}" ] && [ ! -s /data/auth/users.json ]; then
    echo "ERROR: no auth configured. Either create users on the volume" >&2
    echo "  (docker compose run --rm server mlp user add <name> --role admin --root /data)" >&2
    echo "or set ML_PARTY_TOKEN (e.g. -e ML_PARTY_TOKEN=\$(openssl rand -base64 32))" >&2
    exit 1
fi

if [ ! -f /data/store.toml ]; then
    echo "initializing new ml-party store at /data"
    python -c "from mlparty.store import Store; Store.init('/data')"
fi

exec mlp serve --root /data --host 0.0.0.0 --port 7327 "$@"
