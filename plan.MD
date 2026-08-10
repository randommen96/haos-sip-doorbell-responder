Complete Implementation Plan: SIP Doorbell Responder with TTS
Overview
A lightweight Python add-on for Home Assistant OS that acts as a SIP server for your Hikvision KB8113-IME1 doorbell. When the doorbell button is pressed, it answers the call, plays a Text-to-Speech message, hangs up, and publishes an MQTT event for automations. The TTS message is configurable in the add-on UI — change the text, restart the add-on, and the new message is generated at startup via Piper.

Validated Design Decisions (2026-08-10)
Topic	Decision	Why
TTS Engine	Piper (core_piper add-on)	Official HA local TTS. 100% offline, no accounts/keys. ~45 languages.
SIP Library	py3-pjsua (Alpine apk)	Pre-built Python pjsua2 bindings in Alpine main repo. v2.17. No pip compilation needed.
Audio Transcoding	ffmpeg (Alpine apk)	Piper outputs 16kHz PCM WAV. KB8113 only supports G.711 ulaw/alaw. Transcode before playback.
SIP Topology	Add-on acts as SIP registrar	KB8113 registers to the add-on as its "SIP Server". Add-on receives INVITE on button press.
RTP Ports	4000-4001/udp	2 ports = 1 call (RTP + RTCP). PJSIP configured with portRange=1.
KB8113 SIP Compat	Confirmed working	Standard SIP via chan_pjsip. Two-way audio (G.711) works. Not the "XML SDP" model.
TTS Flow	Generate at startup via HA API, cache to file, play on ring	Configurable via add-on UI. Zero per-ring latency. No manual file management.
Part 1: TTS Engine — Piper (Official HA Local TTS)
Piper is the official Home Assistant local TTS engine, maintained under the Open Home Foundation. It is the default TTS for HA Voice.

100% local — neural TTS on-device, no internet, no API keys, no accounts
Official add-on — core_piper in the HA add-on store
~45 languages, 110+ voices, quality tiers: low / medium / high
Custom voice support — drop .onnx + .onnx.json files in /share/piper
Runs via Wyoming protocol on core-piper:10200
Piper Setup (User Side)
Install the Piper add-on from the HA add-on store (core_piper).
Wyoming integration auto-discovers it. Appears as tts.piper entity.
Part 2: TTS Strategy — Generate at Startup, Play on Ring
The add-on generates the TTS audio file once at startup via HA's REST API, transcodes it to G.711, and caches it. Every doorbell press plays the cached file instantly — no API call, no latency.

If HA_TOKEN is configured:
  Startup: POST /api/tts_get_url → HA generates via Piper → download WAV → ffmpeg → cache .ulaw
  On ring: Play cached .ulaw instantly. Zero latency.

If HA_TOKEN is empty:
  Skip API call. Use pre-placed WAV file from /media/tts/ (manual setup).

To change the message: edit tts_message in add-on config, restart add-on. The new audio is generated at startup.
Part 3: Audio Transcoding (ffmpeg)
Piper outputs: PCM WAV, 16kHz sample rate, 16-bit, mono.
KB8113 codec:   G.711 μ-law (PCMU), 8kHz, 8-bit, mono.

Transcode command (same for both modes):
ffmpeg -y -i <input.wav> -acodec pcm_mulaw -ar 8000 -ac 1 /tmp/doorbell_message.ulaw

The .ulaw file is what gets played into the SIP call via RTP.
Part 4: The Python Script (sip_responder.py)
Dependencies
python
import pjsua2 as pj               # SIP — from apk py3-pjsua
import paho.mqtt.client as mqtt   # MQTT — from apk py3-paho-mqtt
import os                          # Environment variables for config
import json                        # MQTT payloads
import subprocess                  # ffmpeg transcoding
import requests                    # HA REST API — from apk py3-requests
import shutil                      # File operations
import tempfile                    # Temporary files for audio download
import time                        # Call state handling
SIP Endpoint Setup
python
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

        elif state == pj.PJSIP_INV_STATE_CONFIRMED:
            print("Call confirmed. Preparing TTS audio...")
            self.play_tts_audio()

        elif state == pj.PJSIP_INV_STATE_DISCONNECTED:
            print("Call disconnected.")
            publish_mqtt_doorbell_state(False)
            self.delete()

    def play_tts_audio(self):
        """Play cached TTS audio into the active call."""
        if self.audio_played:
            return

        if not os.path.exists(TTS_ULAW_PATH):
            print(f"ERROR: Audio file missing: {TTS_ULAW_PATH}")
            self.hangup()
            return
        
        print(f"Playing: {TTS_ULAW_PATH}")
        player = pj.AudioMediaPlayer()
        player.createPlayer(TTS_ULAW_PATH)
        call_media = self.getAudioMedia(-1)
        player.startTransmit(call_media)
        
        self.audio_played = True
        time.sleep(TTS_AUDIO_DURATION)
        self.hangup()
TTS Audio Generation (Startup Only)
python
def generate_tts_audio():
    """Generate TTS audio at startup via HA REST API, transcode, and cache.
    Returns True if a playable .ulaw file is ready."""

    # Mode B: Generate via HA API (if token is configured)
    if HA_TOKEN:
        print(f"Generating TTS via HA API: '{TTS_MESSAGE}'")
        wav_path = fetch_tts_from_ha(TTS_MESSAGE)
        if wav_path:
            ulaw_path = transcode_to_ulaw(wav_path)
            if ulaw_path:
                # Move to the canonical cache path
                shutil.move(ulaw_path, TTS_ULAW_PATH)
                # Clean up temp WAV
                os.remove(wav_path)
                print(f"TTS ready: {TTS_ULAW_PATH}")
                return True

    # Mode A: Use pre-placed WAV file
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

    print("ERROR: No TTS audio source available. Set ha_token or place a WAV in /media/tts/.")
    return False


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
    """Convert a WAV file to G.711 μ-law. Returns path to .ulaw or None."""
    ulaw_path = os.path.join("/tmp", os.path.basename(wav_path).replace(".wav", ".ulaw"))
    result = subprocess.run([
        "ffmpeg", "-y",
        "-i", wav_path,
        "-acodec", "pcm_mulaw",
        "-ar", "8000",
        "-ac", "1",
        ulaw_path,
    ], capture_output=True)
    if result.returncode != 0:
        print(f"ffmpeg error: {result.stderr.decode()}")
        return None
    print(f"Transcoded: {wav_path} → {ulaw_path}")
    return ulaw_path
MQTT Communication
python
DOORBELL_STATE_TOPIC = "doorbell/state"
DISCOVERY_TOPIC = "homeassistant/binary_sensor/doorbell/config"

def publish_mqtt_discovery():
    payload = {
        "name": "Doorbell Pressed",
        "device_class": "sound",
        "state_topic": DOORBELL_STATE_TOPIC,
        "unique_id": "doorbell_responder_pressed"
    }
    mqtt_client.publish(DISCOVERY_TOPIC, json.dumps(payload), retain=True)

def publish_mqtt_doorbell_state(state):
    mqtt_client.publish(DOORBELL_STATE_TOPIC, "ON" if state else "OFF")
Configuration from Environment Variables
python
# SIP
SIP_USERNAME = os.getenv("SIP_USERNAME", "doorbell")
SIP_PASSWORD = os.getenv("SIP_PASSWORD", "change_me")
SIP_DISPLAY_NAME = os.getenv("SIP_DISPLAY_NAME", "Doorbell Responder")
SIP_DOMAIN = os.getenv("SIP_DOMAIN", "192.168.1.100")
SIP_PORT = int(os.getenv("SIP_PORT", "5060"))
RTP_PORT_START = int(os.getenv("RTP_PORT_START", "4000"))

# MQTT
MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# TTS — Mode A (static)
TTS_MESSAGE = os.getenv("TTS_MESSAGE", "Please use the other bell.")
TTS_WAV_PATH = os.getenv("TTS_WAV_PATH", "/media/tts/doorbell_message.wav")
TTS_ULAW_PATH = os.getenv("TTS_ULAW_PATH", "/tmp/doorbell_message.ulaw")
TTS_AUDIO_DURATION = int(os.getenv("TTS_AUDIO_DURATION", "5"))

# TTS — Mode B (dynamic API)
HA_URL = os.getenv("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.getenv("HA_TOKEN", "")  # Empty = Mode A only
TTS_ENGINE = os.getenv("TTS_ENGINE", "tts.piper")
Account Configuration with PJSIP
python
def setup_sip_endpoint():
    ep_cfg = pj.EpConfig()
    ep = pj.Endpoint()
    ep.libCreate()
    ep.libInit(ep_cfg)
    
    sipTpConfig = pj.TransportConfig()
    sipTpConfig.port = SIP_PORT
    ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, sipTpConfig)
    
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
Startup Sequence
python
def main():
    # 1. Connect MQTT
    mqtt_client.connect(MQTT_HOST, MQTT_PORT)
    mqtt_client.loop_start()
    publish_mqtt_discovery()
    
    # 2. Generate and cache TTS audio
    if not generate_tts_audio():
        print("FATAL: No TTS audio available. Add-on will answer calls but play silence.")
    
    # 3. Start SIP endpoint
    ep, acc = setup_sip_endpoint()
    mode = "API (ha_token)" if HA_TOKEN else "static file"
    print(f"SIP ready: {SIP_USERNAME}@{SIP_DOMAIN}:{SIP_PORT}")
    print(f"TTS: {mode} | Message: '{TTS_MESSAGE}' | Duration: {TTS_AUDIO_DURATION}s")
    
    # 4. Event loop
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        ep.libDestroy()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
Part 5: Add-on Configuration (config.yaml)
yaml
name: "SIP Doorbell Responder"
description: "Answers Hikvision KB8113 doorbell rings with a Piper TTS message"
version: "1.0.0"
slug: "sip_responder"
arch:
  - aarch64
  - amd64
  - armhf
  - armv7
  - i386

ports:
  5060/udp: 5060
  4000/udp: 4000
  4001/udp: 4001

host_network: false

options:
  sip_username: "doorbell"
  sip_password: "change_me"
  sip_display_name: "Doorbell Responder"
  sip_domain: "192.168.1.100"
  sip_port: 5060
  rtp_port_start: 4000
  tts_message: "Please use the other bell."
  tts_wav_path: "/media/tts/doorbell_message.wav"
  tts_audio_duration: 5
  ha_url: "http://homeassistant.local:8123"
  ha_token: ""
  tts_engine: "tts.piper"
  mqtt_host: "core-mosquitto"
  mqtt_port: 1883

schema:
  sip_username: str
  sip_password: password
  sip_display_name: str
  sip_domain: str
  sip_port: int
  rtp_port_start: int
  tts_message: str
  tts_wav_path: str
  tts_audio_duration: int
  ha_url: str
  ha_token: str
  tts_engine: str
  mqtt_host: str
  mqtt_port: int

map:
  - media:rw
  - tmp:rw
Part 6: Add-on Files
Dockerfile
dockerfile
FROM ghcr.io/home-assistant/homeassistant-base:latest

RUN apk add --no-cache \
    py3-pjsua \
    ffmpeg \
    py3-paho-mqtt \
    py3-requests

COPY sip_responder.py /
COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
Note: BUILD_FROM is deprecated as of Supervisor 2026.04.0. Using explicit FROM.
run.sh
bash
#!/usr/bin/with-contenv bashio

export SIP_USERNAME=$(bashio::config 'sip_username')
export SIP_PASSWORD=$(bashio::config 'sip_password')
export SIP_DISPLAY_NAME=$(bashio::config 'sip_display_name')
export SIP_DOMAIN=$(bashio::config 'sip_domain')
export SIP_PORT=$(bashio::config 'sip_port')
export RTP_PORT_START=$(bashio::config 'rtp_port_start')
export TTS_MESSAGE=$(bashio::config 'tts_message')
export TTS_WAV_PATH=$(bashio::config 'tts_wav_path')
export TTS_AUDIO_DURATION=$(bashio::config 'tts_audio_duration')
export HA_URL=$(bashio::config 'ha_url')
export HA_TOKEN=$(bashio::config 'ha_token')
export TTS_ENGINE=$(bashio::config 'tts_engine')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')

echo "Starting SIP Doorbell Responder..."
python3 /sip_responder.py
Part 7: Hikvision KB8113 Doorbell Configuration
SIP settings on the doorbell's web interface (Network → Advanced → SIP Settings):

Setting	Value
Enable VOIP Gateway	Checked
SIP Server Address	<HA host IP>
SIP Server Port	5060
SIP Number	doorbell (matches add-on sip_username)
SIP Password	<matches add-on sip_password>
Call Duration	120 seconds
Audio Codec	G.711 μ-law (PCMU)

The doorbell registers to the add-on. On button press, it sends a SIP INVITE.
The add-on answers, plays audio, and hangs up.

KB8113 Compatibility Notes
- Standard SIP works (not the "XML SDP" variant that affects some other Hikvision models)
- Two-way audio confirmed working with chan_pjsip (G.711)
- Re-INVITE handling is buggy on some firmware versions — but our add-on never sends re-INVITEs, so the ~32s drop issue should not trigger
- Doorbell auto-answers incoming calls (not needed for this use case, but good to know)

Part 8: MQTT Binary Sensor Discovery
On startup, the add-on publishes a discovery config (retained). HA auto-creates binary_sensor.doorbell_pressed.

The add-on publishes doorbell/state = "ON" when a call arrives, "OFF" when it disconnects.

Part 9: User Setup Steps
Install Piper add-on (core_piper) from HA add-on store.
Add this add-on repository to HA.
Install "SIP Doorbell Responder" add-on.
Configure options in the add-on UI:
Set sip_domain to your HA host IP.
Set tts_message to whatever you want the doorbell to say.
Create a long-lived token in HA (Profile → Security → Long-lived Access Tokens). Paste it into ha_token.
Configure doorbell SIP settings to point at HA host IP:5060.
Start the add-on. It generates the TTS audio at startup. Press the doorbell to test.
To change the message: edit tts_message in add-on config, restart the add-on.

End-to-End Flow
STARTUP (once):
  Add-on starts
    │
    ▼
  POST /api/tts_get_url → HA generates via Piper → download WAV → ffmpeg → cache .ulaw
    │
    ▼
  SIP endpoint ready. MQTT discovery published.

RING (each press):
  Doorbell button press
    │
    ▼
  KB8113 sends SIP INVITE → Add-on (port 5060)
    │
    ▼
  Add-on publishes MQTT doorbell/state = ON
    │
    ▼
  Add-on answers call (200 OK)
    │
    ▼
  Add-on plays cached .ulaw via RTP (ports 4000-4001)
    │
    ▼
  Add-on hangs up after playback (~5 seconds)
    │
    ▼
  Add-on publishes MQTT doorbell/state = OFF

Files to Create
File	Purpose
repository.yaml	HA add-on repository manifest
sip_responder/config.yaml	Add-on config with options/schema
sip_responder/Dockerfile	Container: apk add py3-pjsua ffmpeg py3-paho-mqtt py3-requests
sip_responder/run.sh	Reads HA options, launches Python
sip_responder/sip_responder.py	Main logic: SIP + MQTT + ffmpeg + TTS
README.md	Full user documentation (see outline below)

README.md Outline
# SIP Doorbell Responder
Brief description of what this add-on does.

## Prerequisites
- Home Assistant OS (or supervised) with Piper add-on installed
- Hikvision KB8113-IME1 doorbell on the same network
- Basic familiarity with HA add-ons and long-lived tokens

## Step 1: Install Piper TTS
1. In HA, go to Settings → Add-ons → Add-on Store
2. Search for "Piper" (official add-on: core_piper)
3. Install and start it
4. Go to Settings → Devices & Services → Integrations
5. Piper should be auto-discovered via Wyoming. If not, add "Wyoming Protocol" manually, pointing to core-piper:10200
6. Verify tts.piper appears in Developer Tools → Services (filter: tts.speak)
7. Recommended voice: en_US-lessac-medium (good quality/speed balance)
   - Or pick from ~110 voices in the Piper add-on config dropdown
   - Custom voices: drop .onnx + .onnx.json files in /share/piper

## Step 2: Create a Long-Lived Access Token
1. In HA, click your profile icon (bottom-left) → Security
2. Scroll to "Long-Lived Access Tokens" → Create Token
3. Name it "SIP Doorbell" and copy the token
4. You will paste this into the add-on config in Step 4

## Step 3: Configure the Hikvision KB8113 Doorbell
1. Find the doorbell's IP (check your router's DHCP list or Hikvision SADP tool)
2. Open a browser to http://<doorbell-ip>
3. Log in (default: admin / check the label on the device)
4. Go to Configuration → Network → Advanced → SIP Settings
5. Configure:

   | Setting | Value |
   |---|---|
   | Enable VOIP Gateway | Checked |
   | SIP Server Address | <Your HA host IP> |
   | SIP Server Port | 5060 |
   | SIP Number | doorbell |
   | SIP Password | (same as sip_password in add-on config) |
   | Transport | UDP |
   | Call Duration | 120 |

6. Save. The status should show "Registered" after the add-on is running.
7. If "Register Failed": double-check the IP, port, and that the add-on is started.

## Step 4: Install and Configure This Add-on
1. Add this repository URL to HA: Settings → Add-ons → Add-on Store → ⋮ → Repositories
2. Install "SIP Doorbell Responder"
3. Go to the add-on's Configuration tab and set:

   | Option | Value |
   |---|---|
   | sip_domain | Your HA host IP (e.g., 192.168.1.100) |
   | sip_username | doorbell (must match the doorbell's SIP Number) |
   | sip_password | Pick a password (must match doorbell's SIP Password) |
   | tts_message | "Please use the other bell." (or whatever you want) |
   | ha_token | Paste the long-lived token from Step 2 |
   | ha_url | http://homeassistant.local:8123 (or your HA URL) |

4. Start the add-on. Check the Log tab:
   - "Generating TTS via HA API" → audio is being generated
   - "TTS ready" → audio cached and ready
   - "SIP ready" → waiting for doorbell rings

## Step 5: Test
1. Press the doorbell button
2. In the add-on logs, you should see:
   - "Doorbell button pressed! Publishing event..."
   - "Call confirmed. Preparing TTS audio..."
   - "Playing: /tmp/doorbell_message.ulaw"
3. The doorbell should speak your message, then hang up
4. In HA, a binary_sensor.doorbell_pressed entity is auto-created via MQTT discovery

## Changing the Message
1. Edit tts_message in the add-on Configuration tab
2. Restart the add-on
3. The new message is generated at startup

## Troubleshooting
- "No TTS audio available" at startup: Check ha_token is valid. Check HA is reachable at ha_url from within the add-on container (use host.docker.internal or the actual IP).
- Doorbell shows "Register Failed": Verify sip_domain is correct and reachable. Check UDP port 5060 is not blocked.
- Call connects but no audio: Verify RTP ports 4000-4001/udp are not blocked. Check doorbell audio codec is set to G.711 μ-law.
- Call drops immediately: Check add-on logs. If no error, check the doorbell firmware version — update to V2.2.60+ if needed.
- Doorbell says "calling failed" (three beeps): In doorbell settings, make sure "Call Management Center" is NOT selected as the default.

## Firewall & Network
- UDP 5060 (SIP signalling) — between doorbell and HA host
- UDP 4000-4001 (RTP audio) — between doorbell and HA host
- TCP 8123 (HA API) — add-on container → HA (for TTS generation at startup)
- If doorbell and HA are on different VLANs/subnets, ensure routing allows these ports

## Automations (Optional)
Use the MQTT binary sensor in HA automations:

```yaml
alias: "Doorbell Press Notification"
trigger:
  - platform: state
    entity_id: binary_sensor.doorbell_pressed
    to: "on"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Doorbell"
      message: "Someone is at the door!"
```
