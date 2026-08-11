#!/usr/bin/env python3
"""
SIP Doorbell Responder for Home Assistant OS.
Answers Hikvision KB8113 doorbell SIP calls and plays a Piper TTS message.
"""

# Unbuffered stdout: Docker pipes are not TTYs, so Python buffers output.
import sys as _sys
_sys.stdout.reconfigure(line_buffering=True)

# Timestamped print for clear log chronology.
import time
import builtins as _bi
_orig_print = _bi.print


def _ts_print(*args, **kwargs):
    _orig_print(time.strftime("%H:%M:%S"), *args, **kwargs)


_bi.print = _ts_print


def _ts_print(*args, **kwargs):
    ts = time.strftime("%H:%M:%S")
    _orig_print(f"{ts}", *args, **kwargs)


_bi.print = _ts_print

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

# Configuration loader — separate module for testability (no pjsua2 dep)
from config import load_options, OPTIONS_PATH  # noqa: E402

cfg = load_options()

SIP_USERNAME = cfg["sip_username"]
SIP_PASSWORD = cfg["sip_password"]
SIP_DISPLAY_NAME = cfg["sip_display_name"]
SIP_DOMAIN = cfg["sip_domain"]
SIP_PORT = cfg["sip_port"]
RTP_PORT_START = cfg["rtp_port_start"]
LOG_LEVEL = cfg["log_level"]

MQTT_HOST = cfg["mqtt_host"]
MQTT_PORT = cfg["mqtt_port"]
MQTT_USERNAME = cfg["mqtt_username"]
MQTT_PASSWORD = cfg["mqtt_password"]


def discover_mqtt_broker():
    """Try to auto-discover HA's built-in MQTT broker via Supervisor API.
    Returns (host, port, username, password) or None if not available."""
    token = _os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        print("MQTT: no SUPERVISOR_TOKEN, cannot auto-discover broker.")
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
            print(f"MQTT broker discovered via Supervisor: {host}:{port}" +
                  (" (auth)" if user else " (no auth)"))
            return host, port, user, pwd
        else:
            print(f"MQTT broker discovery failed: HTTP {resp.status_code}")
            print(f"  Response: {resp.text[:200]}")
    except Exception as e:
        print(f"MQTT broker discovery error: {e}")
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

mqtt_client = mqtt.Client(client_id="sip_doorbell_responder")
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

def _on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        print("MQTT connected.")
        publish_mqtt_discovery()
    elif rc == 5:
        print("MQTT connection refused: not authorized (rc=5).")
        print("  Configure mqtt_username and mqtt_password in the app settings.")
    else:
        print(f"MQTT connection failed (rc={rc})")

def _on_mqtt_disconnect(client, userdata, rc):
    if rc != 0:
        print(f"MQTT disconnected (rc={rc}), auto-reconnecting...")

mqtt_client.on_connect = _on_mqtt_connect
mqtt_client.on_disconnect = _on_mqtt_disconnect


def publish_mqtt_discovery():
    """Publish MQTT discovery config so HA auto-creates the binary sensor."""
    uid = "doorbell_responder_pressed"
    name = cfg.get("sensor_name", "Doorbell Pressed")
    payload = {
        "name": name,
        "device_class": "sound",
        "state_topic": DOORBELL_STATE_TOPIC,
        "payload_on": "ON",
        "payload_off": "OFF",
        "unique_id": uid,
        "off_delay": 10,  # keep ON for 10s max, then auto-off
    }
    topic = f"homeassistant/binary_sensor/{uid}/config"
    msg = mqtt_client.publish(topic, json.dumps(payload), qos=1, retain=True)
    if msg.rc == mqtt.MQTT_ERR_SUCCESS:
        print("MQTT discovery published (retained).")
        print(f"  Topic: {topic}")
        print(f"  State topic: {DOORBELL_STATE_TOPIC}")
        print(f"  Entity: binary_sensor.doorbell_pressed")
    else:
        print(f"MQTT discovery failed: rc={msg.rc}")


def publish_mqtt_doorbell_state(state):
    """Publish ON/OFF to the doorbell state topic."""
    payload = "ON" if state else "OFF"
    msg = mqtt_client.publish(DOORBELL_STATE_TOPIC, payload, qos=1)
    print(f"MQTT publish: {DOORBELL_STATE_TOPIC} = {payload} (rc={msg.rc})")


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

# Persistent storage for Call objects. The pjsua2 Python bindings have a
# documented GC issue: if a Call is garbage-collected after onIncomingCall
# returns, PJSIP auto-rejects with 603 Decline.
_active_calls = {}

# Module-level endpoint reference for event processing during playback.
_endpoint = None


class DoorbellAccount(pj.Account):
    def onRegState(self, prm):
        if prm.code == 200:
            print("SIP registration OK — doorbell can now connect.")
        # 408 = self-registration timeout: normal, no registrar module.
        # The registration still adds our URI to the location table,
        # which is needed for incoming INVITE matching. Don't log noise.

    def onIncomingCall(self, prm):
        call = DoorbellCall(self, prm.callId)
        # Store to prevent Python GC. The pjsua2 docs warn: if a Call
        # object is garbage-collected, PJSIP auto-rejects with 603.
        _active_calls[prm.callId] = call
        print("Doorbell button pressed! Publishing event...")
        publish_mqtt_doorbell_state(True)
        call_prm = pj.CallOpParam()
        call_prm.statusCode = 200
        call.answer(call_prm)
        print("Call answered (200 OK).")
        return call


class DoorbellCall(pj.Call):
    def __init__(self, acc, call_id):
        pj.Call.__init__(self, acc, call_id)
        self.audio_played = False

    def onCallState(self, prm):
        state = self.getInfo().state

        if state == pj.PJSIP_INV_STATE_CONFIRMED:
            print("Call confirmed. Playing TTS audio...")
            self.play_tts_audio()

        elif state == pj.PJSIP_INV_STATE_DISCONNECTED:
            print("Call disconnected.")
            publish_mqtt_doorbell_state(False)
            _active_calls.pop(self.getId(), None)

    def play_tts_audio(self):
        """Play cached mu-law audio into the active call."""
        if self.audio_played:
            return
        if not os.path.exists(TTS_ULAW_PATH):
            print(f"ERROR: Audio file missing: {TTS_ULAW_PATH}")
            hangup_prm = pj.CallOpParam()
            self.hangup(hangup_prm)
            return

        print(f"Playing: {TTS_ULAW_PATH}")
        file_size = os.path.getsize(TTS_ULAW_PATH)
        duration = file_size / 8000
        print(f"  File: {file_size} bytes, ~{duration:.1f}s")

        # Brief delay for conference ports to link. The doorbell's RTP
        # stream is already negotiated, but the conference connection
        # occasionally takes longer on some calls. 200ms ensures the
        # first audio frames are never lost — even for sub-second messages.
        deadline = time.time() + 0.2
        while time.time() < deadline:
            if _endpoint:
                _endpoint.libHandleEvents(10)

        try:
            player = pj.AudioMediaPlayer()
            player.createPlayer(TTS_ULAW_PATH, options=1)
            call_media = self.getAudioMedia(-1)
            player.startTransmit(call_media)
        except pj.Error as e:
            print(f"PJSIP playback error: {e}")
            hangup_prm = pj.CallOpParam()
            self.hangup(hangup_prm)
            return

        self.audio_played = True

        # Process events briefly so the conference connection completes
        # before we start sleeping. Without this, short files (<3s) can
        # miss the first ~100ms while ports are being connected.
        deadline = time.time() + duration + 0.5
        while time.time() < deadline:
            if _endpoint:
                _endpoint.libHandleEvents(50)
            else:
                time.sleep(0.05)

        hangup_prm = pj.CallOpParam()
        self.hangup(hangup_prm)
        print("Hung up after playback.")


# ---------------------------------------------------------------------------
# SIP endpoint setup
# ---------------------------------------------------------------------------

def setup_sip_endpoint():
    ep_cfg = pj.EpConfig()
    # threadCnt=0 is required for Python: pjsua2's worker threads don't
    # dispatch to Python callbacks. With 0 threads, the main thread
    # handles all SIP events and our onCallState/onIncomingCall fire.
    ep_cfg.uaConfig.threadCnt = 0
    # Suppress PJSIP detail logs (REGISTER retries, endpoint/module init).
    # Level 2 = WARNING, suppresses the ~40 lines of INFO per startup.
    ep_cfg.logConfig.level = LOG_LEVEL
    ep_cfg.logConfig.consoleLevel = LOG_LEVEL
    ep = pj.Endpoint()
    ep.libCreate()
    ep.libInit(ep_cfg)

    sip_tp_config = pj.TransportConfig()
    sip_tp_config.port = SIP_PORT
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sip_tp_config)

    ep.audDevManager().setNullDev()
    ep.libStart()

    acfg = pj.AccountConfig()
    acfg.idUri = f"sip:{SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}"
    # No self-registration — the GC fix (store Call objects) was the
    # real 603 fix. Registration adds 408 timeout noise on every cycle.
    acfg.mediaConfig.transportConfig.port = RTP_PORT_START
    acfg.mediaConfig.transportConfig.portRange = 1
    acfg.videoConfig.autoShowIncoming = False
    acfg.videoConfig.autoTransmitOutgoing = False
    acfg.videoConfig.autoTransmitOutgoing = False

    acc = DoorbellAccount()
    acc.create(acfg)
    print(f"SIP account created: {acfg.idUri}")
    global _endpoint
    _endpoint = ep
    return ep, acc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("--- SIP Doorbell Responder ---")
    print(f"Config loaded from {OPTIONS_PATH}")
    print(f"  SIP: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    print(f"  PJSIP log level: {LOG_LEVEL} (0=fatal, 5=verbose)")
    mqtt_src = "auto" if (not MQTT_HOST or MQTT_HOST == "core-mosquitto") else "manual"
    print(f"  MQTT: {MQTT_HOST}:{MQTT_PORT} [{mqtt_src}]" + (" (auth)" if MQTT_USERNAME else ""))
    print(f"  TTS: '{TTS_MESSAGE}' ({TTS_AUDIO_DURATION}s)" + (" [API]" if SUPERVISOR_TOKEN else " [static file]"))

    # 1. Connect MQTT — auto-discover HA built-in broker if not configured
    mqtt_host = MQTT_HOST
    mqtt_port = MQTT_PORT
    mqtt_user = MQTT_USERNAME
    mqtt_pass = MQTT_PASSWORD

    if mqtt_user:
        print(f"MQTT: using configured credentials for {mqtt_host}:{mqtt_port}")
    elif not mqtt_host or mqtt_host == "core-mosquitto":
        print("MQTT: no credentials configured, trying Supervisor service discovery...")
        discovered = discover_mqtt_broker()
        if discovered:
            mqtt_host, mqtt_port, mqtt_user, mqtt_pass = discovered
            print(f"MQTT: using discovered broker {mqtt_host}:{mqtt_port}")
        else:
            print("MQTT: Supervisor discovery failed — broker may require auth.")
            print("  If connection fails, set mqtt_username and mqtt_password")
            print("  in the app configuration (Mosquitto add-on -> Configuration).")

    try:
        if mqtt_user:
            mqtt_client.username_pw_set(mqtt_user, mqtt_pass)
        mqtt_client.connect_async(mqtt_host, mqtt_port, keepalive=30)
        mqtt_client.loop_start()
        print(f"MQTT connecting to {mqtt_host}:{mqtt_port}" +
              (" (authenticated)" if mqtt_user else " (no auth)"))
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        print("Continuing without MQTT — doorbell state will not be published.")

    # 2. Generate TTS audio at startup
    if not generate_tts_audio():
        print("FATAL: No TTS audio available. App will answer calls but play silence.")

    # 3. Start SIP endpoint
    ep, acc = setup_sip_endpoint()
    mode = "API" if SUPERVISOR_TOKEN else "static file"
    print(f"SIP listening: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    print(f"TTS: {mode} | Message: '{TTS_MESSAGE}' | Duration: {TTS_AUDIO_DURATION}s")
    print("Waiting for doorbell rings...")

    # 4. Event loop — with threadCnt=0, we must poll for SIP events
    try:
        while True:
            ep.libHandleEvents(100)  # 100ms timeout, non-blocking poll
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        ep.libDestroy()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("Stopped.")


if __name__ == "__main__":
    main()
