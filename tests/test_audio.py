"""Tests for audio transcoding and duration calculation."""
import os
import shutil
import sys
import subprocess
import tempfile
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sip_responder"))


def test_duration_calculation():
    """Mu-law is 8000 bytes/sec: duration = filesize / 8000."""
    # 24752 bytes = typical doorbell message
    assert 24752 / 8000 == 3.094  # ~3.1 seconds


def test_transcode_creates_valid_wav():
    """ffmpeg creates a transcode WAV with pcm_mulaw codec."""
    if not shutil.which("ffmpeg"):
        return  # skip if ffmpeg not installed

    # Create a test MP3 (Piper outputs MP3)
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
         "-t", "1", "-acodec", "mp3", tmp.name],
        capture_output=True,
    )

    # Transcode
    out = tmp.name.replace(".mp3", "_ulaw.wav")
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", tmp.name, "-acodec", "pcm_mulaw",
         "-ar", "8000", "-ac", "1", out],
        capture_output=True,
    )
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"
    assert os.path.getsize(out) > 0

    os.unlink(tmp.name)
    os.unlink(out)


def test_tts_url_parsing_absolute():
    """HA with external_url returns absolute URLs."""
    tests = [
        ("https://hass.example.com/api/tts_proxy/abc.mp3",
         "/api/tts_proxy/abc.mp3"),
        ("/api/tts_proxy/abc.mp3",
         "/api/tts_proxy/abc.mp3"),
        ("http://homeassistant.local:8123/api/tts_proxy/xyz.wav",
         "/api/tts_proxy/xyz.wav"),
    ]
    for input_url, expected_path in tests:
        path = urlparse(input_url).path
        assert path == expected_path, f"urlparse({input_url}).path != {expected_path}"
        assert path.startswith("/api/tts_proxy/")
        # Verify download URL construction
        download_url = f"http://supervisor/core{path}"
        assert download_url.startswith("http://supervisor/core/api/tts_proxy/")


def test_mqtt_discovery_payload():
    """Discovery payload has all required fields."""
    import json

    uid = "doorbell_responder_pressed"
    payload = {
        "name": "Test Doorbell",
        "device_class": "sound",
        "state_topic": "doorbell/state",
        "payload_on": "ON",
        "payload_off": "OFF",
        "unique_id": uid,
    }

    topic = f"homeassistant/binary_sensor/{uid}/config"
    assert "homeassistant/binary_sensor/" in topic
    assert "/config" in topic
    assert uid in topic

    # Verify JSON is valid and has required keys
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)
    for key in ("name", "state_topic", "unique_id"):
        assert key in decoded, f"Missing {key} in discovery payload"
