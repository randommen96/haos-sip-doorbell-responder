"""Unit tests for config.load_options()."""
import json
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sip_responder"))
import config  # noqa: E402
from config import normalize_sip_uri, retry_with_backoff  # noqa: E402


def test_defaults():
    """When no options.json exists, defaults are returned."""
    opts = config.load_options()
    assert opts["sip_username"] == "doorbell"
    assert opts["sip_password"] == "change_me"
    assert opts["sip_domain"] == "192.168.1.100"
    assert opts["sip_port"] == 5060
    assert opts["rtp_port_start"] == 4000
    assert opts["tts_message"] == "Please use the other bell."
    assert opts["tts_audio_duration"] == 5
    assert opts["tts_engine"] == "tts.piper"
    assert opts["tts_voice"] == ""
    assert opts["mqtt_host"] == ""
    assert opts["mqtt_port"] == 1883
    assert opts["sensor_name"] == "Doorbell Pressed"
    assert opts["log_level"] == 1
    assert opts["mqtt_username"] == ""
    assert opts["mqtt_password"] == ""
    assert opts["mqtt_listen_topic"] == "doorbell/announce"
    assert opts["outbound_sip_uri"] == ""
    assert opts["tts_retry_enabled"] is True
    assert opts["tts_retry_max_attempts"] == 0
    assert opts["tts_retry_initial_delay"] == 5
    assert opts["tts_retry_max_delay"] == 300


def test_custom_values():
    """Custom options.json values override defaults."""
    custom = {
        "sip_username": "mybell",
        "tts_message": "Go away!",
        "log_level": 5,
    }
    path = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False).name
    with open(path, "w") as f:
        json.dump(custom, f)

    try:
        config.OPTIONS_PATH = path
        opts = config.load_options()
        assert opts["sip_username"] == "mybell"
        assert opts["tts_message"] == "Go away!"
        assert opts["log_level"] == 5
        # unchanged defaults
        assert opts["sip_domain"] == "192.168.1.100"
        assert opts["mqtt_port"] == 1883
    finally:
        os.unlink(path)


def test_all_config_keys():
    """Every config.yaml option must have a default."""
    required = {
        "sip_username", "sip_password", "sip_display_name", "sip_domain",
        "sip_port", "rtp_port_start", "tts_message", "tts_wav_path",
        "tts_audio_duration", "tts_engine", "tts_voice", "mqtt_host",
        "mqtt_port", "sensor_name", "log_level", "mqtt_username", "mqtt_password",
        "mqtt_listen_topic", "outbound_sip_uri", "tts_retry_enabled",
        "tts_retry_max_attempts", "tts_retry_initial_delay", "tts_retry_max_delay",
    }
    opts = config.load_options()
    missing = required - set(opts.keys())
    assert not missing, f"Missing defaults: {missing}"


def test_normalize_sip_uri():
    """Bare hosts get sip: prepended; sip:/sips: pass through; empty stays empty."""
    assert normalize_sip_uri("") == ""
    assert normalize_sip_uri("  ") == ""
    assert normalize_sip_uri("192.168.1.64") == "sip:192.168.1.64"
    assert normalize_sip_uri("doorbell@192.168.1.50:5060") == "sip:doorbell@192.168.1.50:5060"
    assert normalize_sip_uri("sip:doorbell@192.168.1.50") == "sip:doorbell@192.168.1.50"
    assert normalize_sip_uri("sips:secure@host") == "sips:secure@host"
    assert normalize_sip_uri("SIP:UPPERCASE") == "SIP:UPPERCASE"


def test_retry_with_backoff_succeeds_first_try():
    """Returns result immediately on first success, no sleep."""
    calls = []
    result = retry_with_backoff(
        lambda: (calls.append(1), "ok")[1],
        "test", True, 5, 300, 0,
    )
    assert result == "ok"
    assert len(calls) == 1


def test_retry_with_backoff_eventually_succeeds():
    """Retries until the function returns truthy."""
    attempts = [0]

    def fail_then_succeed():
        attempts[0] += 1
        if attempts[0] < 3:
            return None
        return "success"

    result = retry_with_backoff(
        fail_then_succeed, "test", True, 0.01, 0.02, 0,
    )
    assert result == "success"
    assert attempts[0] == 3


def test_retry_with_backoff_disabled():
    """With enabled=False, only one attempt is made."""
    calls = []
    result = retry_with_backoff(
        lambda: (calls.append(1), None)[1],
        "test", False, 5, 300, 0,
    )
    assert result is None
    assert len(calls) == 1


def test_retry_with_backoff_max_attempts():
    """Gives up after max_attempts failures."""
    attempts = [0]

    def always_fail():
        attempts[0] += 1
        return None

    result = retry_with_backoff(
        always_fail, "test", True, 0.01, 0.02, 3,
    )
    assert result is None
    assert attempts[0] == 3  # immediate try + 2 retries = 3 total
