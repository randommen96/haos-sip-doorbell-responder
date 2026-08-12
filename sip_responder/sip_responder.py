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
import queue
import threading

# Configuration loader — separate module for testability (no pjsua2 dep)
from config import (  # noqa: E402
    load_options, OPTIONS_PATH,
    normalize_sip_uri, retry_with_backoff,
)

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

# MQTT trigger — outbound call feature
MQTT_LISTEN_TOPIC = cfg.get("mqtt_listen_topic", "")
OUTBOUND_SIP_URI = cfg.get("outbound_sip_uri", "")

# TTS retry — exponential backoff for startup and on-demand generation
TTS_RETRY_ENABLED = cfg.get("tts_retry_enabled", True)
TTS_RETRY_MAX_ATTEMPTS = cfg.get("tts_retry_max_attempts", 0)
TTS_RETRY_INITIAL_DELAY = cfg.get("tts_retry_initial_delay", 5)
TTS_RETRY_MAX_DELAY = cfg.get("tts_retry_max_delay", 300)
OUTBOUND_CALL_TIMEOUT = 30  # seconds without answer before we CANCEL

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
        if MQTT_LISTEN_TOPIC:
            mqtt_client.subscribe(MQTT_LISTEN_TOPIC, qos=1)
            print(f"MQTT subscribed: {MQTT_LISTEN_TOPIC} (outbound trigger)")
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


def _on_mqtt_message(client, userdata, msg):
    """Outbound trigger. Runs on paho's network thread — must NOT touch
    pjsua2. Only thread-safe work here: parse payload, spawn a TTS worker
    thread, and hand the result to the main thread via outbound_queue."""
    if not MQTT_LISTEN_TOPIC:
        return
    if msg.retain:
        print("MQTT: ignoring retained message (stale trigger).")
        return
    payload = msg.payload.decode("utf-8", errors="replace").strip()
    if not payload:
        print("MQTT: empty payload ignored.")
        return
    if not OUTBOUND_SIP_URI:
        print("ERROR: outbound_sip_uri not configured — outbound call skipped.")
        return
    print(f"MQTT: outbound trigger: '{payload}'")
    threading.Thread(target=_outbound_tts_worker, args=(payload,),
                     daemon=True).start()


def _outbound_tts_worker(message):
    """Generate TTS for an outbound trigger, retrying with backoff. Runs in
    a daemon thread; on success hands the audio to the main thread via the
    queue. Never touches pjsua2 or the shared TTS cache file."""
    if not SUPERVISOR_TOKEN:
        print("ERROR: no SUPERVISOR_TOKEN — cannot generate outbound TTS.")
        return
    ulaw_path = retry_with_backoff(
        lambda: _generate_outbound_audio(message),
        f"Outbound TTS '{message[:30]}'",
        TTS_RETRY_ENABLED, TTS_RETRY_INITIAL_DELAY,
        TTS_RETRY_MAX_DELAY, TTS_RETRY_MAX_ATTEMPTS,
    )
    if ulaw_path:
        _outbound["queue"].put({"message": message, "ulaw_path": ulaw_path})
    else:
        print(f"Outbound TTS failed — call skipped for: '{message}'")


mqtt_client.on_message = _on_mqtt_message


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


def _generate_outbound_audio(message):
    """Fetch TTS for an outbound message and transcode to mu-law. Returns a
    unique /tmp path or None. Thread-safe: every file it creates is derived
    from a fresh NamedTemporaryFile, so concurrent workers never collide and
    the shared startup cache (TTS_ULAW_PATH) is never touched."""
    wav_path = fetch_tts_from_ha(message)
    if not wav_path:
        return None
    try:
        return transcode_to_ulaw(wav_path)
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)


def remove_audio_file(path):
    """Best-effort cleanup of a per-call audio file (any thread)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError as e:
        print(f"WARN: could not remove {path}: {e}")


def _startup_tts_worker():
    """Background startup TTS. Tries once immediately, then retries with
    exponential backoff so Piper warm-up (add-on starts before Piper, HA
    API routing, model loading) is covered. On success the cached mu-law
    file simply exists — incoming calls detect it via the existing
    os.path.exists() check in play_audio_in_call."""
    if not SUPERVISOR_TOKEN and not os.path.exists(TTS_WAV_PATH):
        print("ERROR: No TTS source (no SUPERVISOR_TOKEN, no pre-placed WAV).")
        print("  Incoming calls will hang up without audio.")
        return
    ok = retry_with_backoff(
        generate_tts_audio, "TTS",
        TTS_RETRY_ENABLED, TTS_RETRY_INITIAL_DELAY,
        TTS_RETRY_MAX_DELAY, TTS_RETRY_MAX_ATTEMPTS,
    )
    if not ok:
        print("FATAL: No TTS audio available. App will answer calls but play silence.")


# ---------------------------------------------------------------------------
# SIP — PJSIP callbacks
# ---------------------------------------------------------------------------

# Persistent storage for Call objects. The pjsua2 Python bindings have a
# documented GC issue: if a Call is garbage-collected after onIncomingCall
# returns, PJSIP auto-rejects with 603 Decline.
_active_calls = {}

# Module-level endpoint reference for event processing during playback.
_endpoint = None
_account = None  # set by setup_sip_endpoint()

# Doorbell SIP URI discovered from incoming calls — used as the default
# outbound_sip_uri when the user hasn't configured one explicitly.
_discovered_doorbell_uri = None

# Outbound call state — all read/written only in the main thread.
# pjsua2 is not thread-safe, so the MQTT callback only enqueues jobs;
# the main event loop drains the queue and places calls.
# Single mutable dict avoids 'global' declarations — we mutate contents,
# never reassign the _outbound name itself.
_outbound = {
    "queue": queue.Queue(),
    "active": False,
    "start_time": 0,
    "call_id": None,
    "job": None,  # pending job waiting for line to free up
}


def play_audio_in_call(call, ulaw_path):
    """Play a mu-law WAV into an active call, then hang up. Main thread only.
    Shared by incoming (DoorbellCall) and outbound (OutboundCall) calls."""
    if getattr(call, "audio_played", False):
        return
    call.audio_played = True
    if not os.path.exists(ulaw_path):
        print(f"ERROR: Audio file missing: {ulaw_path}")
        hangup_prm = pj.CallOpParam()
        call.hangup(hangup_prm)
        return

    print(f"Playing: {ulaw_path}")
    file_size = os.path.getsize(ulaw_path)
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
        player.createPlayer(ulaw_path, options=1)
        call_media = call.getAudioMedia(-1)
        player.startTransmit(call_media)
    except pj.Error as e:
        print(f"PJSIP playback error: {e}")
        hangup_prm = pj.CallOpParam()
        call.hangup(hangup_prm)
        return

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
    call.hangup(hangup_prm)
    print("Hung up after playback.")


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

        # Learn the doorbell's SIP URI for outbound calls.
        # Use remoteContact (the Contact header) — that's the doorbell's
        # actual reachable address.  remoteUri is the From header which
        # carries the SIP identity with our domain, not the doorbell's IP.
        global _discovered_doorbell_uri
        info = call.getInfo()
        if info.remoteContact and not _discovered_doorbell_uri:
            _discovered_doorbell_uri = info.remoteContact
            print(f"Outbound SIP URI discovered: {_discovered_doorbell_uri}")

        call_prm = pj.CallOpParam()
        if _outbound["active"] or len(_active_calls) > 1:
            # This call is already in the dict, so len>1 means another
            # call is in progress; _outbound["active"] gives the reason.
            reason = "outbound call in progress" if _outbound["active"] \
                     else "another call in progress"
            call_prm.statusCode = 486
            print(f"Busy ({reason}) — rejecting incoming call with 486.")
        else:
            call_prm.statusCode = 200
            print("Call answered (200 OK).")
        call.answer(call_prm)
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
        play_audio_in_call(self, TTS_ULAW_PATH)


class OutboundCall(pj.Call):
    """Outbound call triggered by an MQTT message. Plays the generated TTS
    audio once CONFIRMED. Same GC-fix discipline as incoming calls: the
    instance must be kept in _active_calls or pjsua2 abandons the call."""

    def __init__(self, acc, ulaw_path):
        pj.Call.__init__(self, acc, pj.PJSUA_INVALID_ID)
        self.ulaw_path = ulaw_path
        self.audio_played = False

    def onCallState(self, prm):
        state = self.getInfo().state
        if state == pj.PJSIP_INV_STATE_CONFIRMED:
            print("Outbound call confirmed. Playing TTS audio...")
            play_audio_in_call(self, self.ulaw_path)
        elif state == pj.PJSIP_INV_STATE_DISCONNECTED:
            info = self.getInfo()
            print(f"Outbound call disconnected. (last status: {info.lastStatusCode})")
            _active_calls.pop(self.getId(), None)
            _outbound["active"] = False
            _outbound["call_id"] = None
            remove_audio_file(self.ulaw_path)


# ---------------------------------------------------------------------------
# Outbound call placement and main-loop processing
# ---------------------------------------------------------------------------


def start_outbound_call(job):
    """Place the outbound call. Main thread only — called from
    process_outbound_requests. Stores the call for the GC fix."""
    # Resolve URI: explicit config > auto-discovered from incoming call
    uri = normalize_sip_uri(OUTBOUND_SIP_URI) or normalize_sip_uri(
        _discovered_doorbell_uri or ""
    )
    if not uri:
        print("ERROR: no outbound SIP URI — configure outbound_sip_uri"
              " or wait for a doorbell ring to auto-discover it.")
        remove_audio_file(job["ulaw_path"])
        return
    call = OutboundCall(_account, job["ulaw_path"])
    call_prm = pj.CallOpParam()
    try:
        call.makeCall(uri, call_prm)
    except pj.Error as e:
        print(f"Outbound call error: {e}")
        remove_audio_file(job["ulaw_path"])
        return
    _active_calls[call.getId()] = call  # GC fix applies to outbound too
    _outbound["active"] = True
    _outbound["start_time"] = time.time()
    _outbound["call_id"] = call.getId()
    print(f"Outbound call placed: {uri} (call id {call.getId()})")


def process_outbound_requests():
    """Called from the main loop every iteration. Drains the MQTT->main
    queue (latest message wins), starts a pending call once the line is
    free, and enforces the outbound answer timeout. All SIP operations
    stay on the main thread — pjsua2 is not thread-safe."""

    # Drain the queue, keeping only the most recent job.
    try:
        while True:
            job = _outbound["queue"].get_nowait()
            if _outbound["job"] is not None:
                remove_audio_file(_outbound["job"]["ulaw_path"])  # superseded
            _outbound["job"] = job
    except queue.Empty:
        pass

    # Start the pending call once no call is in progress. An in-progress
    # incoming call simply delays this; the check re-runs next iteration.
    if _outbound["job"] is not None and not _active_calls:
        job = _outbound["job"]
        _outbound["job"] = None
        start_outbound_call(job)

    # Give up on unanswered outbound calls (doorbell never auto-answered).
    if (_outbound["active"]
            and time.time() - _outbound["start_time"] > OUTBOUND_CALL_TIMEOUT):
        print("Outbound call timed out (no answer). Hanging up.")
        print("  Check the doorbell's SIP auto-answer setting.")
        call = _active_calls.get(_outbound["call_id"])
        if call:
            hangup_prm = pj.CallOpParam()
            call.hangup(hangup_prm)
        _outbound["active"] = False


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
    # Port range for RTP/RTCP pairs. One pair for the account (always
    # reserved), one pair for the active call (inbound or outbound —
    # mutual exclusion guarantees only one at a time).
    acfg.mediaConfig.transportConfig.portRange = 2
    # Session timers disabled: KB8113 YATE stack has broken re-INVITE
    # handling (known 32-second drop from Asterisk community).  Set
    # expires=0 and min=90 to pass PJSIP's internal assertion while
    # still avoiding timer-triggered re-INVITEs.
    acfg.callConfig.timerMinSESec = 90
    acfg.callConfig.timerSessExpiresSec = 0
    acfg.videoConfig.autoShowIncoming = False
    acfg.videoConfig.autoTransmitOutgoing = False

    acc = DoorbellAccount()
    acc.create(acfg)
    print(f"SIP account created: {acfg.idUri}")
    global _endpoint, _account
    _endpoint = ep
    _account = acc
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
    if MQTT_LISTEN_TOPIC:
        uri_txt = OUTBOUND_SIP_URI or "(auto-discover on first ring)"
        print(f"  Outbound calls: topic '{MQTT_LISTEN_TOPIC}' -> {uri_txt}")
    else:
        print("  Outbound calls: disabled (mqtt_listen_topic empty)")
    print(f"  TTS retry: {'enabled' if TTS_RETRY_ENABLED else 'disabled'} "
          f"(attempts={'infinite' if TTS_RETRY_MAX_ATTEMPTS == 0 else TTS_RETRY_MAX_ATTEMPTS}, "
          f"delay {TTS_RETRY_INITIAL_DELAY}s -> {TTS_RETRY_MAX_DELAY}s)")

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

    # 2. Generate TTS audio at startup — background thread with retry.
    #    SIP startup is never blocked; Piper warm-up is covered by retries.
    threading.Thread(target=_startup_tts_worker, daemon=True).start()

    # 3. Start SIP endpoint
    ep, acc = setup_sip_endpoint()
    mode = "API" if SUPERVISOR_TOKEN else "static file"
    print(f"SIP listening: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    print(f"TTS: {mode} | Message: '{TTS_MESSAGE}' | Duration: {TTS_AUDIO_DURATION}s")
    print("Waiting for doorbell rings...")

    # 4. Event loop — with threadCnt=0, we must poll for SIP events.
    #    Outbound requests are drained here (main thread) because pjsua2
    #    is not thread-safe: MQTT callbacks only enqueue jobs.
    try:
        while True:
            ep.libHandleEvents(100)  # 100ms timeout, non-blocking poll
            process_outbound_requests()
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        ep.libDestroy()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("Stopped.")


if __name__ == "__main__":
    main()
