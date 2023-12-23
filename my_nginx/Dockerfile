ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache nginx openssl

COPY rootfs /

CMD [ "/run.sh" ]
