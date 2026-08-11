#!/usr/bin/env python3
"""
SIP Doorbell Responder for Home Assistant OS.
Answers Hikvision KB8113 doorbell SIP calls and plays a Piper TTS message.
"""

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
        "sip_display_name": "Doorbell Responder",
        "sip_domain": "192.168.1.100",
        "sip_port": 5060,
        "rtp_port_start": 4000,
        "tts_message": "Please use the other bell.",
        "tts_wav_path": "/media/tts/doorbell_message.wav",
        "tts_audio_duration": 5,
        "ha_url": "http://homeassistant.local:8123",
        "ha_token": "",
        "tts_engine": "tts.piper",
        "mqtt_host": "core-mosquitto",
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

TTS_MESSAGE = cfg["tts_message"]
TTS_WAV_PATH = cfg["tts_wav_path"]
TTS_ULAW_PATH = "/tmp/doorbell_message.ulaw"
TTS_AUDIO_DURATION = cfg["tts_audio_duration"]

HA_URL = cfg["ha_url"].rstrip("/")
HA_TOKEN = cfg["ha_token"]
TTS_ENGINE = cfg["tts_engine"]

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
    """Call HA REST API to generate TTS and download the WAV. Returns path or None."""
    try:
        resp = requests.post(
            f"{HA_URL}/api/tts_get_url",
            headers={
                "Authorization": f"Bearer {HA_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "engine_id": TTS_ENGINE,
                "message": message,
                "cache": True,
            },
            timeout=15,
        )
        resp.raise_for_status()
        tts_url = resp.json().get("url")
        if not tts_url:
            print("ERROR: No URL in TTS response")
            return None

        audio_resp = requests.get(
            f"{HA_URL}{tts_url}",
            headers={"Authorization": f"Bearer {HA_TOKEN}"},
            timeout=15,
        )
        audio_resp.raise_for_status()

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(audio_resp.content)
        tmp.close()
        print(f"Downloaded TTS WAV: {tmp.name}")
        return tmp.name

    except requests.RequestException as e:
        print(f"HA API error: {e}")
        return None


def transcode_to_ulaw(wav_path):
    """Convert a WAV file to G.711 mu-law. Returns path to .ulaw or None."""
    ulaw_path = os.path.join(
        "/tmp", os.path.basename(wav_path).replace(".wav", ".ulaw")
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
    if HA_TOKEN:
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
        print(f"Registration state: {prm.reason}")


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

    acfg = pj.AccountConfig()
    acfg.idUri = f"sip:{SIP_USERNAME}@{SIP_DOMAIN}"
    acfg.regConfig.registrarUri = f"sip:{SIP_DOMAIN}:{SIP_PORT}"
    acfg.sipConfig.authCreds.append(
        pj.AuthCredInfo("digest", "*", SIP_USERNAME, 0, SIP_PASSWORD)
    )
    acfg.mediaConfig.transportConfig.port = RTP_PORT_START
    acfg.mediaConfig.transportConfig.portRange = 1

    acc = DoorbellAccount()
    acc.create(acfg)
    return ep, acc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # 1. Connect MQTT
    try:
        if MQTT_USERNAME:
            mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        publish_mqtt_discovery()
    except Exception as e:
        print(f"MQTT connection failed: {e}")
        print("Continuing without MQTT — doorbell state will not be published.")

    # 2. Generate TTS audio at startup
    if not generate_tts_audio():
        print("FATAL: No TTS audio available. App will answer calls but play silence.")

    # 3. Start SIP endpoint
    ep, acc = setup_sip_endpoint()
    mode = "API (ha_token)" if HA_TOKEN else "static file"
    print(f"SIP ready: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
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
