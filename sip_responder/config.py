"""Configuration loader for SIP Doorbell Responder.
Reads HA add-on options from /data/options.json with sensible defaults.
This module has zero external dependencies — safe to import in tests."""

import json

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
        "tts_engine": "tts.piper",
        "tts_voice": "",
        "mqtt_host": "",
        "mqtt_port": 1883,
        "sensor_name": "Doorbell Pressed",
        "log_level": 1,
        "mqtt_username": "",
        "mqtt_password": "",
    }
    try:
        with open(OPTIONS_PATH) as f:
            opts = json.load(f)
        merged = {**defaults, **opts}
        return {k: merged.get(k, defaults[k]) for k in defaults}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Cannot read {OPTIONS_PATH}: {e}")
        print("Falling back to environment variables / defaults.")
        return defaults
