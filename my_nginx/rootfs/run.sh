#!/usr/bin/with-contenv bashio

set -e

bashio::log.info "Running nginx..."
exec nginx -c /nginx.conf < /dev/null
