FROM ghcr.io/home-assistant/homeassistant-base:latest

RUN apk add --no-cache \
    py3-pjsua \
    ffmpeg \
    py3-paho-mqtt \
    py3-requests

COPY sip_responder.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
