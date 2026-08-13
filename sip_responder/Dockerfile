FROM ghcr.io/home-assistant/homeassistant-base:2026.07.0

# apk installs Python packages to /usr/lib, but this image's Python
# looks in /usr/local/lib. A .pth file reliably adds the path at
# Python startup regardless of environment (ENV vars can be stripped
# by s6-overlay).
RUN echo "/usr/lib/python3.14/site-packages" \
        > /usr/local/lib/python3.14/site-packages/apk-packages.pth

# Suppress JACK client connection noise in headless container.
# ALSA noise is suppressed in Python via snd_lib_error_set_handler().
ENV PULSE_SERVER=none
ENV JACK_NO_START_SERVER=1

RUN apk add --no-cache \
    py3-pjsua \
    ffmpeg \
    py3-paho-mqtt \
    py3-requests \
    curl

# go2rtc — ISAPI two-way audio for outbound TTS playback
ARG TARGETARCH
RUN case "${TARGETARCH}" in \
        amd64) G2RTC="go2rtc_linux_amd64" ;; \
        arm64) G2RTC="go2rtc_linux_arm64" ;; \
        *) echo "unsupported arch ${TARGETARCH}"; exit 1 ;; \
    esac \
    && curl -L -o /usr/local/bin/go2rtc \
        "https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/${G2RTC}" \
    && chmod +x /usr/local/bin/go2rtc

COPY config.py /
COPY sip_responder.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
