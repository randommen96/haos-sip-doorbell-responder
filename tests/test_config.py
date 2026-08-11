"""Unit tests for config.load_options()."""
import json
import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sip_responder"))
import config  # noqa: E402


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
    }
    opts = config.load_options()
    missing = required - set(opts.keys())
    assert not missing, f"Missing defaults: {missing}"
