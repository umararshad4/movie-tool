#!/bin/sh
# Start the Movie Tool: the local service and the Exact web app together.
# The app prints its address (default http://127.0.0.1:8765).
set -e
cd "$(dirname "$0")"
python3 service/server.py &
SVC=$!
trap 'kill $SVC 2>/dev/null' EXIT
cd movie-tool
exec bun exact.mjs web
