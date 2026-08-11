FROM ghcr.io/home-assistant/homeassistant-base:latest

# apk installs Python packages to /usr/lib, but this image's Python
# looks in /usr/local/lib. A .pth file reliably adds the path at
# Python startup regardless of environment (ENV vars can be stripped
# by s6-overlay).
RUN echo "/usr/lib/python3.14/site-packages" \
        > /usr/local/lib/python3.14/site-packages/apk-packages.pth

RUN apk add --no-cache \
    py3-pjsua \
    ffmpeg \
    py3-paho-mqtt \
    py3-requests

COPY sip_responder.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
