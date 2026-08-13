FROM ghcr.io/home-assistant/homeassistant-base:2026.07.0

# apk installs Python packages to /usr/lib, but this image's Python
# looks in /usr/local/lib. A .pth file reliably adds the path at
# Python startup regardless of environment (ENV vars can be stripped
# by s6-overlay).
RUN echo "/usr/lib/python3.14/site-packages" \
        > /usr/local/lib/python3.14/site-packages/apk-packages.pth

# Suppress JACK client connection noise in headless container.
# ALSA noise: without a sound card, PortAudio walks a fallback list of
# PCM names (sysdefault, front, rear, ...) and each resolves through the
# stock ALSA config hooks, printing ~60 "cannot find card '0' / Unknown
# PCM" errors per startup and per call. Overriding only 'default' is not
# enough (verified) — every name in the fallback list must map to null.
# A few JACK probe lines (~5, startup only) remain and are not
# suppressible without rebuilding PortAudio.
ENV PULSE_SERVER=none
ENV JACK_NO_START_SERVER=1

RUN printf '%s\n' \
        'pcm.!default { type null }' \
        'ctl.!default { type null }' \
        'pcm.!sysdefault { type null }' \
        'pcm.!front { type null }' \
        'pcm.!rear { type null }' \
        'pcm.!center_lfe { type null }' \
        'pcm.!side { type null }' \
        'pcm.!surround21 { type null }' \
        'pcm.!surround40 { type null }' \
        'pcm.!surround41 { type null }' \
        'pcm.!surround50 { type null }' \
        'pcm.!surround51 { type null }' \
        'pcm.!surround71 { type null }' \
        'pcm.!iec958 { type null }' \
        'pcm.!spdif { type null }' \
        'pcm.!hdmi { type null }' \
        'pcm.!modem { type null }' \
        'pcm.!phoneline { type null }' \
        'pcm.!dmix { type null }' \
        'pcm.!pulse { type null }' \
        > /etc/asound.conf

RUN apk add --no-cache \
    py3-pjsua \
    ffmpeg \
    py3-paho-mqtt \
    py3-requests

COPY config.py /
COPY sip_responder.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
