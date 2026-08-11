#!/usr/bin/env python3
"""
SIP Doorbell Responder for Home Assistant OS.
Answers Hikvision KB8113 doorbell SIP calls and plays a Piper TTS message.
"""

# Unbuffered stdout: Docker pipes are not TTYs, so Python buffers output.
# Without this, log lines may not appear until process exit.
import sys as _sys
_sys.stdout.reconfigure(line_buffering=True)

# Suppress PulseAudio/JACK client connection noise in headless container.
# ALSA noise (~60 lines of card scan / virtual PCM spam) is harmless
# and we cannot safely suppress it (ctypes ALSA error handler causes
# segfaults on some platforms due to va_list ABI mismatch).
import os as _os
_os.environ.setdefault("PULSE_SERVER", "none")
_os.environ.setdefault("JACK_NO_START_SERVER", "1")

import pjsua2 as pj
import paho.mqtt.client as mqtt
import os
import json
import subprocess
import requests
import shutil
import tempfile
import time

# ---------------------------------------------------------------------------
# Configuration — read from HA options.json (mounted at /data/options.json)
# ---------------------------------------------------------------------------

OPTIONS_PATH = "/data/options.json"


def load_options():
    """Load and return HA add-on options, with defaults."""
    defaults = {
        "sip_username": "doorbell",
        "sip_password": "change_me",
        "sip_extensions": "",
        "sip_display_name": "Doorbell Responder",
        "sip_domain": "192.168.1.100",
        "sip_port": 5060,
        "rtp_port_start": 4000,
        "tts_message": "Please use the other bell.",
        "tts_wav_path": "/media/tts/doorbell_message.wav",
        "tts_audio_duration": 5,
        "tts_engine": "tts.piper",
        "tts_voice": "",
        "mqtt_host": "",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
    }
    try:
        with open(OPTIONS_PATH) as f:
            opts = json.load(f)
        # Merge with defaults (HA options take precedence)
        merged = {**defaults, **opts}
        # Filter to only known keys
        return {k: merged.get(k, defaults[k]) for k in defaults}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Cannot read {OPTIONS_PATH}: {e}")
        print("Falling back to environment variables / defaults.")
        return defaults


cfg = load_options()

SIP_USERNAME = cfg["sip_username"]
SIP_PASSWORD = cfg["sip_password"]
SIP_DISPLAY_NAME = cfg["sip_display_name"]
SIP_DOMAIN = cfg["sip_domain"]
SIP_PORT = cfg["sip_port"]
RTP_PORT_START = cfg["rtp_port_start"]

MQTT_HOST = cfg["mqtt_host"]
MQTT_PORT = cfg["mqtt_port"]
MQTT_USERNAME = cfg["mqtt_username"]
MQTT_PASSWORD = cfg["mqtt_password"]


def discover_mqtt_broker():
    """Try to auto-discover HA's built-in MQTT broker via Supervisor API.
    Returns (host, port, username, password) or None if not available."""
    token = _os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return None
    try:
        resp = requests.get(
            "http://supervisor/services/mqtt",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            host = data.get("host", "core-mosquitto")
            port = data.get("port", 1883)
            user = data.get("username", "")
            pwd = data.get("password", "")
            print(f"MQTT broker discovered via Supervisor: {host}:{port}")
            return host, port, user, pwd
    except Exception as e:
        print(f"MQTT discovery skipped: {e}")
    return None

TTS_MESSAGE = cfg["tts_message"]
TTS_WAV_PATH = cfg["tts_wav_path"]
TTS_ULAW_PATH = "/tmp/doorbell_message_ulaw.wav"
TTS_AUDIO_DURATION = cfg["tts_audio_duration"]
TTS_ENGINE = cfg["tts_engine"]
TTS_VOICE = cfg.get("tts_voice", "")

# Supervisor-injected token — automatically available to all add-ons.
# Used to call HA Core API via the internal proxy at http://supervisor/core/api/
SUPERVISOR_TOKEN = _os.environ.get("SUPERVISOR_TOKEN", "")

# Internal Supervisor proxy URL for HA Core API (no user config needed)
HA_API_URL = "http://supervisor/core/api"

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

DOORBELL_STATE_TOPIC = "doorbell/state"
DISCOVERY_TOPIC = "homeassistant/binary_sensor/doorbell/config"

mqtt_client = mqtt.Client(client_id="sip_doorbell_responder")


def publish_mqtt_discovery():
    """Publish MQTT discovery config so HA auto-creates the binary sensor."""
    payload = {
        "name": "Doorbell Pressed",
        "device_class": "sound",
        "state_topic": DOORBELL_STATE_TOPIC,
        "unique_id": "doorbell_responder_pressed",
    }
    mqtt_client.publish(DISCOVERY_TOPIC, json.dumps(payload), retain=True)
    print("MQTT discovery published.")


def publish_mqtt_doorbell_state(state):
    """Publish ON/OFF to the doorbell state topic."""
    mqtt_client.publish(DOORBELL_STATE_TOPIC, "ON" if state else "OFF")


# ---------------------------------------------------------------------------
# TTS — audio generation at startup
# ---------------------------------------------------------------------------

def fetch_tts_from_ha(message):
    """Call HA Core API (via Supervisor proxy) to generate TTS and download
    the WAV. Uses the auto-injected SUPERVISOR_TOKEN — no user token needed."""
    try:
        voice_info = f" voice={TTS_VOICE}" if TTS_VOICE else ""
        print(f"TTS: POST {HA_API_URL}/tts_get_url engine={TTS_ENGINE}{voice_info}")
        body = {
            "engine_id": TTS_ENGINE,
            "message": message,
            "cache": True,
        }
        if TTS_VOICE:
            body["options"] = {"voice": TTS_VOICE}
        resp = requests.post(
            f"{HA_API_URL}/tts_get_url",
            headers={
                "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"TTS API error: HTTP {resp.status_code}")
            print(f"  URL: {HA_API_URL}/tts_get_url")
            print(f"  Response: {resp.text[:500]}")
            return None
        data = resp.json()
        tts_url = data.get("url")
        if not tts_url:
            print(f"ERROR: No 'url' in TTS response. Got keys: {list(data.keys())}")
            print(f"  Full response: {json.dumps(data)[:500]}")
            return None

        # Download the audio file. HA may return a relative path
        # (/api/tts_proxy/...) or an absolute URL if external_url
        # is configured. We always route through the Supervisor proxy
        # because SUPERVISOR_TOKEN only works internally.
        from urllib.parse import urlparse
        path = urlparse(tts_url).path  # strip scheme/host, keep /api/tts_proxy/...
        download_url = f"http://supervisor/core{path}"
        print(f"TTS: downloading audio from {download_url}")
        audio_resp = requests.get(
            download_url,
            headers={"Authorization": f"Bearer {SUPERVISOR_TOKEN}"},
            timeout=15,
        )
        if audio_resp.status_code != 200:
            print(f"TTS audio download error: HTTP {audio_resp.status_code}")
            print(f"  URL: {download_url}")
            print(f"  Response: {audio_resp.text[:500]}")
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".audio", delete=False)
        tmp.write(audio_resp.content)
        tmp.close()
        print(f"Downloaded TTS WAV: {tmp.name}")
        return tmp.name

    except requests.RequestException as e:
        print(f"HA API error: {e}")
        return None


def transcode_to_ulaw(wav_path):
    """Convert an audio file (WAV or MP3 from Piper) to G.711 mu-law in a
    WAV container. Returns path to the transcoded file or None."""
    ulaw_path = os.path.join(
        "/tmp", os.path.basename(wav_path).rsplit(".", 1)[0] + "_ulaw.wav"
    )
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", wav_path,
            "-acodec", "pcm_mulaw",
            "-ar", "8000",
            "-ac", "1",
            ulaw_path,
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr.decode()}")
        return None
    print(f"Transcoded: {wav_path} -> {ulaw_path}")
    return ulaw_path


def generate_tts_audio():
    """Generate TTS audio at startup and cache as mu-law. Returns True if ready."""
    if SUPERVISOR_TOKEN:
        print(f"Generating TTS via HA API: '{TTS_MESSAGE}'")
        wav_path = fetch_tts_from_ha(TTS_MESSAGE)
        if wav_path:
            ulaw_path = transcode_to_ulaw(wav_path)
            if ulaw_path:
                shutil.move(ulaw_path, TTS_ULAW_PATH)
                os.remove(wav_path)
                print(f"TTS ready: {TTS_ULAW_PATH}")
                return True

    # Fallback: use pre-placed file
    if os.path.exists(TTS_ULAW_PATH):
        print(f"Using existing cached file: {TTS_ULAW_PATH}")
        return True

    if os.path.exists(TTS_WAV_PATH):
        print(f"Transcoding pre-placed WAV: {TTS_WAV_PATH}")
        ulaw_path = transcode_to_ulaw(TTS_WAV_PATH)
        if ulaw_path:
            shutil.move(ulaw_path, TTS_ULAW_PATH)
            print(f"TTS ready: {TTS_ULAW_PATH}")
            return True

    print("ERROR: No TTS audio source available.")
    return False


# ---------------------------------------------------------------------------
# SIP — PJSIP callbacks
# ---------------------------------------------------------------------------

class DoorbellAccount(pj.Account):
    def onRegState(self, prm):
        # prm.code is SIP status code (200 = OK, 408 = timeout, etc.)
        if prm.code == 200:
            print("SIP registration OK — doorbell can now connect.")
        else:
            print(f"SIP registration event: code={prm.code} reason={prm.reason}")


class DoorbellCall(pj.Call):
    def __init__(self, acc, call_id):
        pj.Call.__init__(self, acc, call_id)
        self.audio_played = False

    def onCallState(self, prm):
        state = self.info().state

        if state == pj.PJSIP_INV_STATE_INCOMING:
            print("Doorbell button pressed! Publishing event...")
            publish_mqtt_doorbell_state(True)
            call_prm = pj.CallOpParam()
            call_prm.statusCode = 200
            self.answer(call_prm)
            print("Call answered (200 OK).")

        elif state == pj.PJSIP_INV_STATE_CONFIRMED:
            print("Call confirmed. Playing TTS audio...")
            self.play_tts_audio()

        elif state == pj.PJSIP_INV_STATE_DISCONNECTED:
            print("Call disconnected.")
            publish_mqtt_doorbell_state(False)
            self.delete()

    def play_tts_audio(self):
        """Play cached mu-law audio into the active call."""
        if self.audio_played:
            return
        if not os.path.exists(TTS_ULAW_PATH):
            print(f"ERROR: Audio file missing: {TTS_ULAW_PATH}")
            self.hangup()
            return

        print(f"Playing: {TTS_ULAW_PATH}")
        try:
            player = pj.AudioMediaPlayer()
            player.createPlayer(TTS_ULAW_PATH)
            call_media = self.getAudioMedia(-1)
            player.startTransmit(call_media)
        except pj.Error as e:
            print(f"PJSIP playback error: {e}")
            self.hangup()
            return

        self.audio_played = True
        time.sleep(TTS_AUDIO_DURATION)
        self.hangup()
        print("Hung up after playback.")


# ---------------------------------------------------------------------------
# SIP endpoint setup
# ---------------------------------------------------------------------------

def setup_sip_endpoint():
    ep_cfg = pj.EpConfig()
    ep = pj.Endpoint()
    ep.libCreate()
    ep.libInit(ep_cfg)

    sip_tp_config = pj.TransportConfig()
    sip_tp_config.port = SIP_PORT
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_config)

    ep.audDevManager().setNullDev()
    ep.libStart()

    # Create an account for each extension we want to accept calls for.
    # The doorbell calls a specific number (configured in its Number
    # Settings). We listen on the configured username AND the common
    # doorbell defaults 6001/6002.
    extensions = {SIP_USERNAME}
    extensions.update(cfg.get("sip_extensions", "").replace(" ", "").split(","))
    # Always include common doorbell defaults
    extensions.update({"6001", "6002"})
    extensions.discard("")  # remove empty string if any

    for ext in extensions:
        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{ext}@{SIP_DOMAIN}:{SIP_PORT}"
        # Do NOT set registrarUri — we don't register to anyone.
        # We just listen for incoming INVITEs matching these URIs.
        acfg.mediaConfig.transportConfig.port = RTP_PORT_START
        acfg.mediaConfig.transportConfig.portRange = 1
        acc = DoorbellAccount()
        acc.create(acfg)
        print(f"SIP account created: {acfg.idUri}")

    print(f"SIP listening on {len(extensions)} extension(s)")
    return ep


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("--- SIP Doorbell Responder ---")
    print(f"Config loaded from {OPTIONS_PATH}")
    print(f"  SIP: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    mqtt_src = "auto" if (not MQTT_HOST or MQTT_HOST == "core-mosquitto") else "manual"
    print(f"  MQTT: {MQTT_HOST}:{MQTT_PORT} [{mqtt_src}]" + (" (auth)" if MQTT_USERNAME else ""))
    print(f"  TTS: '{TTS_MESSAGE}' ({TTS_AUDIO_DURATION}s)" + (" [API]" if SUPERVISOR_TOKEN else " [static file]"))

    # 1. Connect MQTT — auto-discover HA built-in broker if not configured
    mqtt_host = MQTT_HOST
    mqtt_port = MQTT_PORT
    mqtt_user = MQTT_USERNAME
    mqtt_pass = MQTT_PASSWORD
    if not mqtt_host or mqtt_host == "core-mosquitto":
        discovered = discover_mqtt_broker()
        if discovered:
            mqtt_host, mqtt_port, mqtt_user, mqtt_pass = discovered
    try:
        if mqtt_user:
            mqtt_client.username_pw_set(mqtt_user, mqtt_pass)
        mqtt_client.connect(mqtt_host, mqtt_port, 60)
        mqtt_client.loop_start()
        publish_mqtt_discovery()
        print(f"MQTT connected: {mqtt_host}:{mqtt_port}")
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        print("Continuing without MQTT — doorbell state will not be published.")

    # 2. Generate TTS audio at startup
    if not generate_tts_audio():
        print("FATAL: No TTS audio available. App will answer calls but play silence.")

    # 3. Start SIP endpoint
    ep = setup_sip_endpoint()
    mode = "API" if SUPERVISOR_TOKEN else "static file"
    print(f"SIP listening: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    print(f"TTS: {mode} | Message: '{TTS_MESSAGE}' | Duration: {TTS_AUDIO_DURATION}s")
    print("Waiting for doorbell rings...")

    # 4. Event loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        ep.libDestroy()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("Stopped.")


if __name__ == "__main__":
    main()
