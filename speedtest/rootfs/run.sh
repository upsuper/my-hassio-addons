#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Starting Speedtest HTTP API on port 8080"
exec python3 /server.py
