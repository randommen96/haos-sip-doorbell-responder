"""Configuration loader for SIP Doorbell Responder.
Reads HA add-on options from /data/options.json with sensible defaults.
This module has zero external dependencies — safe to import in tests."""

import json
import time

OPTIONS_PATH = "/data/options.json"


def load_options():
    """Load and return HA add-on options, with defaults."""
    defaults = {
        "sip_username": "responder",
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
        "mqtt_listen_topic": "doorbell/announce",
        "outbound_sip_uri": "",
        "tts_retry_enabled": True,
        "tts_retry_max_attempts": 0,
        "tts_retry_initial_delay": 5,
        "tts_retry_max_delay": 300,
    }
    try:
        with open(OPTIONS_PATH) as f:
            opts = json.load(f)
        merged = {**defaults, **opts}
        result = {k: merged.get(k, defaults[k]) for k in defaults}
        # Clamp retry values — guard against bogus Supervisor input.
        result["tts_retry_max_attempts"] = max(0, int(result["tts_retry_max_attempts"]))
        result["tts_retry_initial_delay"] = max(1, int(result["tts_retry_initial_delay"]))
        result["tts_retry_max_delay"] = max(1, int(result["tts_retry_max_delay"]))
        return result
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARNING: Cannot read {OPTIONS_PATH}: {e}")
        print("Falling back to environment variables / defaults.")
        return defaults


# ---------------------------------------------------------------------------
# Pure helpers — no external deps, testable in CI (no pjsua2 required).
# ---------------------------------------------------------------------------


def normalize_sip_uri(uri):
    """Ensure a SIP URI has a scheme. Accepts 'sip:...', 'sips:...', or bare
    host/user@host (which gets 'sip:' prepended). Empty string stays empty."""
    uri = (uri or "").strip()
    if not uri:
        return ""
    if not uri.lower().startswith(("sip:", "sips:")):
        uri = "sip:" + uri
    return uri


def retry_with_backoff(attempt_fn, name, enabled,
                       initial_delay, max_delay, max_attempts):
    """Call attempt_fn() until it returns a truthy value, backing off
    exponentially (initial_delay * 2^n, capped at max_delay). With
    enabled=False it tries exactly once. max_attempts=0 means retry forever.
    Returns the first truthy result, or None on final failure."""
    delay = initial_delay
    failures = 0
    while True:
        result = attempt_fn()
        if result:
            return result
        if not enabled:
            return None
        failures += 1
        if max_attempts > 0 and failures >= max_attempts:
            print(f"{name}: gave up after {failures} failed attempt(s).")
            return None
        print(f"{name}: attempt {failures} failed - retrying in {delay}s...")
        time.sleep(delay)
        delay = min(delay * 2, max_delay)
