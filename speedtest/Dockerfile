ARG BUILD_FROM
FROM ${BUILD_FROM}

ARG BUILD_ARCH
ARG SPEEDTEST_VERSION
ARG SPEEDTEST_SHA256_AARCH64
ARG SPEEDTEST_SHA256_AMD64

RUN apk add --no-cache curl python3 \
    && case "${BUILD_ARCH}" in \
        aarch64) SPEEDTEST_ARCH="aarch64"; SPEEDTEST_SHA256="${SPEEDTEST_SHA256_AARCH64}" ;; \
        amd64) SPEEDTEST_ARCH="x86_64"; SPEEDTEST_SHA256="${SPEEDTEST_SHA256_AMD64}" ;; \
        *) echo "Unsupported architecture: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac \
    && SPEEDTEST_URL="https://install.speedtest.net/app/cli/ookla-speedtest-${SPEEDTEST_VERSION}-linux-${SPEEDTEST_ARCH}.tgz" \
    && curl -fsSL "${SPEEDTEST_URL}" -o /tmp/speedtest.tgz \
    && echo "${SPEEDTEST_SHA256}  /tmp/speedtest.tgz" | sha256sum -c - \
    && tar -xzf /tmp/speedtest.tgz -C /usr/local/bin speedtest \
    && chmod 0755 /usr/local/bin/speedtest \
    && rm /tmp/speedtest.tgz

COPY rootfs /

CMD [ "/run.sh" ]
