#!/usr/bin/with-contenv bashio

set -e

SECRET_PATH=/data/secret
CONFIG_PATH=/navidrome.toml

# Generate secret for password encryption
if ! bashio::fs.file_exists "${SECRET_PATH}"; then
    pwgen 64 1 > "${SECRET_PATH}"
fi

# Prepare config file
sed -i "s#%%MUSIC_FOLDER%%#$(bashio::config "music_folder")#g" "${CONFIG_PATH}"
sed -i "s#%%BASE_URL%%#$(bashio::config "base_url")#g" "${CONFIG_PATH}"
sed -i "s/%%DEFAULT_LANGUAGE%%/$(bashio::config "default_language")/g" "${CONFIG_PATH}"
sed -i "s/%%ENABLE_SHARING%%/$(bashio::config "enable_sharing")/g" "${CONFIG_PATH}"
sed -i "s/%%ENABLE_STAR_RATING%%/$(bashio::config "enable_star_rating")/g" "${CONFIG_PATH}"
sed -i "s/%%ENABLE_FAVOURITES%%/$(bashio::config "enable_favourites")/g" "${CONFIG_PATH}"
sed -i "s/%%ENABLE_USER_EDITING%%/$(bashio::config "enable_user_editing")/g" "${CONFIG_PATH}"
sed -i "s/%%SECRET%%/$(cat "${SECRET_PATH}")/g" "${CONFIG_PATH}"

mkdir -p /data/cache

# Start server
exec /navidrome \
    --cachefolder /data/cache \
    --configfile "${CONFIG_PATH}" \
    --datafolder /config

