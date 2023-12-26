ARG BUILD_FROM
FROM $BUILD_FROM

ARG BUILD_ARCH
ARG NAVIDROME_VERSION
RUN apk add --no-cache ffmpeg pwgen \
    && ARCH="${BUILD_ARCH}" \
    && if [[ "${BUILD_ARCH}" = "aarch64" ]]; then ARCH="arm64"; fi \
    && URL="https://github.com/navidrome/navidrome/releases/download/v${NAVIDROME_VERSION}/navidrome_${NAVIDROME_VERSION}_linux_${ARCH}.tar.gz" \
    && echo "Downloading ${URL}..." \
    && curl -L -s "${URL}" | tar -zxvf - navidrome -C /

COPY rootfs /

CMD [ "/run.sh" ]
