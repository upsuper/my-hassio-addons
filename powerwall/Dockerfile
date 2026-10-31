FROM ghcr.io/home-assistant/base:3.22

RUN apk add --no-cache python3 py3-pip \
    && python3 -m venv /opt/venv

COPY requirements.txt /requirements.txt
RUN /opt/venv/bin/pip install --no-cache-dir -r /requirements.txt

COPY rootfs /

CMD [ "/opt/venv/bin/python", "/server.py" ]
