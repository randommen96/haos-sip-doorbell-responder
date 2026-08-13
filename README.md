# SIP Doorbell Responder

Home Assistant app (add-on) that answers SIP calls from a Hikvision KB8113-IME1 doorbell, plays a text-to-speech message via Piper, and publishes MQTT events for automations.

## How It Works

1. At startup, the app generates a TTS audio file via HA's TTS API (Piper) using the auto-injected Supervisor token, transcodes it to G.711 mu-law, and caches it.
2. When the doorbell button is pressed, the doorbell sends a SIP INVITE to the app.
3. The app answers, plays the cached audio, hangs up, and publishes `doorbell/state = ON/OFF` via MQTT.
4. Home Assistant auto-discovers `binary_sensor.doorbell_pressed` for use in automations.

## Prerequisites

- Home Assistant OS (or supervised installation)
- Hikvision KB8113-IME1 doorbell on the same network
- Piper TTS add-on installed (see Step 1)

## Step 1: Install Piper TTS

1. In HA, go to **Settings** -> **Add-ons** -> **Add-on Store**
2. Search for **Piper** (official add-on: `core_piper`)
3. Install and start it
4. Go to **Settings** -> **Devices & Services** -> **Integrations**
5. Piper should be auto-discovered via Wyoming. If not, add "Wyoming Protocol" manually and point it to `core-piper:10200`
6. Verify `tts.piper` appears in **Developer Tools** -> **Services** (filter: `tts.speak`)
7. Recommended voice: `en_US-lessac-medium` (good quality/speed balance). Configure in the Piper add-on settings.
   - Custom voices can be placed in `/share/piper` (`.onnx` + `.onnx.json` files)

## Step 2: Configure the Hikvision KB8113 Doorbell

1. Find the doorbell's IP address (check your router's DHCP list, or use the Hikvision SADP tool)
2. Open a browser to `http://<doorbell-ip>`
3. Log in (default credentials are on the device label)

### SIP Settings

4. Go to **Configuration** -> **Network** -> **Basic Settings** -> **SIP**
5. Configure:

| Setting | Value |
|---|---|
| Enable VOIP Gateway | Checked |
| Register User Name | `doorbell` (the doorbell's own identity — any value) |
| Registration Password | Any value — the app does not verify registration |
| Server Address | `<Your HA host IP>` |
| Server Port | `5060` |
| Number | `doorbell` |
| Display User Name | `voordeur` (or whatever you prefer) |

6. Save.

### Button Call Target

7. Go to **Intercom** -> **Number Settings** -> **Add**
8. Configure:

| Setting | Value |
|---|---|
| Room No. | `1` |
| SIP Number | `responder` (must match app's `sip_username`) |

9. Save.
10. Go to **Intercom** -> **Press Button to Call**
11. Select: **Call Specified Indoor Station** -> choose the room you just created (`1`)

The doorbell does not need to show "Registered" — it sends an INVITE directly on button press regardless of registration status.

### Disable Relay Click

The doorbell clicks a relay on button press by default. To silence it: go to **Intercom → I/O Settings**, set **I/O Output → Output1** to **Electric Lock** (not Mechanical Doorbell). The relay won't click. Also set **Access Control → Door Parameters → Open Duration** to `1` second to minimize any pulse.

## Step 3: Install and Configure This App

1. Add this repository URL to HA: **Settings** -> **Add-ons** -> **Add-on Store** -> **...** (menu) -> **Repositories**
2. Enter: `https://github.com/randommen96/haos-sip-doorbell-responder`
3. Install "SIP Doorbell Responder"
4. Go to the app's **Configuration** tab and set:

| Option | Value |
|---|---|
| `sip_domain` | Your HA host IP (e.g., `192.168.1.100`) |
| `sip_username` | `responder` (our identity — the doorbell calls this) |
| `tts_message` | What you want the doorbell to say |
| `tts_voice` | Piper voice (e.g., `en_US-lessac-medium`). Empty = Piper default |
| `sensor_name` | Name for the MQTT binary sensor entity |
| `log_level` | PJSIP log level: 0=fatal, 1=error (default), 2=warning, 3=info, 4=debug, 5=trace |
| `mqtt_username` | MQTT broker username (leave empty for auto-discovery) |
| `mqtt_password` | MQTT broker password (leave empty for auto-discovery) |

> No access token or MQTT credentials needed — the app uses the Supervisor to auto-provision both.

### Log Levels

The default `log_level: 1` (ERROR) suppresses all PJSIP noise except actual errors. Only raise for debugging:

| Level | What you see |
|---|---|
| 0 | Fatal errors only |
| 1 | Errors |
| 2 | Warnings — quiet startup, ~3 lines |
| 3 | Info — shows module registration |
| 4 | Debug — detailed call flow |
| 5 | Trace — every SIP message including REGISTER retries |

5. Start the app. Check the **Log** tab — you should see:
   - `--- SIP Doorbell Responder ---`
   - `SIP: doorbell@<ip>:5060`
   - `TTS: '...' [API]`
   - `Generating TTS via HA API: '...'`
   - `TTS ready: /tmp/doorbell_message_ulaw.wav`
   - `SIP ready: doorbell@<ip>:5060`
   - `Waiting for doorbell rings...`

## Step 4: Test

1. Press the doorbell button
2. In the app logs, you should see:
   - `Doorbell button pressed! Publishing event...`
   - `Call answered (200 OK).`
   - `Call confirmed. Playing TTS audio...`
   - `Playing: /tmp/doorbell_message_ulaw.wav`
   - `Hung up after playback.`
   - `Call disconnected.`
3. The doorbell should speak your message, then hang up
4. In HA, `binary_sensor.doorbell_pressed` appears automatically via MQTT discovery

## Changing the Message

1. Edit `tts_message` in the app's **Configuration** tab
2. Restart the app
3. The new audio is generated at startup

## Firewall & Network

These ports must be reachable:

| Port | Protocol | Between |
|---|---|---|
| 5060 | UDP | Doorbell -> HA host (SIP signalling) |
| 4000-4001 | UDP | Doorbell -> HA host (RTP audio) |
| 8123 | TCP | App container -> HA (TTS API at startup) |

If your doorbell and HA are on different VLANs/subnets, ensure routing allows these.

## Automations

The MQTT binary sensor can be used in HA automations:

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

```yaml
alias: "Doorbell Press — Flash Lights"
trigger:
  - platform: state
    entity_id: binary_sensor.doorbell_pressed
    to: "on"
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room
    data:
      flash: short
```

## MQTT-Triggered Outbound Audio

You can make the doorbell speak arbitrary messages by publishing to an MQTT topic:

1. Set `doorbell_admin_username` (default `admin`) and `doorbell_admin_password` (doorbell web UI password)
2. `mqtt_listen_topic` defaults to `doorbell/announce`. `doorbell_ip` is optional — auto-discovered on the first ring.
3. Publish a message to the topic — the app generates TTS and plays it on the doorbell speaker via Hikvision ISAPI two-way audio (no SIP call needed)

Use in automations:

```yaml
action:
  - service: mqtt.publish
    data:
      topic: doorbell/announce
      payload: "Package delivered, please collect at the front door."
```

### Results

Each announcement publishes its terminal result to `mqtt_result_topic` (default `doorbell/announce/result`):

```json
{"id": "", "status": "ok", "message": "Package delivered...", "error": ""}
```

`status` is `ok` (played on the doorbell) or `error` (reason in `error`, e.g. `TTS generation failed`, `ISAPI playback failed`). Results are not retained — they are transient events.

To match a result to the request that caused it, publish a JSON payload with an `id` — the app echoes it in the result:

```yaml
action:
  - service: mqtt.publish
    data:
      topic: doorbell/announce
      payload: '{"id": "package-announce", "text": "Package delivered, please collect at the front door."}'
```

```yaml
alias: "React to announcement result"
trigger:
  - platform: mqtt
    topic: doorbell/announce/result
    value_template: "{{ value_json.id }}"
    payload: "package-announce"
action:
  - if:
      - condition: template
        value_template: "{{ trigger.payload_json.status == 'ok' }}"
    then:
      - service: notify.notify
        data:
          message: "Announcement played on the doorbell."
    else:
      - service: notify.notify
        data:
          message: "Announcement failed: {{ trigger.payload_json.error }}"
```

Plain-text payloads keep working as before (result gets an empty `id`, the full text is echoed in `message`).

## TTS Retry

If Piper isn't ready when the app starts, TTS generation retries with exponential backoff (5s → 300s cap, configurable). Once it succeeds, the cached audio is available for incoming doorbell presses. Check the log for "TTS ready after N retries."

## Troubleshooting

| Symptom | Likely Cause |
|---|---|
| "No TTS audio available" at startup | TTS API call failed. Check Piper add-on is installed and running. The app log will show the specific error. |
| Doorbell shows "Register Failed" | `sip_domain` IP is wrong or unreachable. Check UDP 5060 is not firewalled. |
| Call connects but no audio | RTP ports 4000-4001/udp blocked. Doorbell audio codec not set to G.711 mu-law. |
| Call drops immediately | Check app logs. Update doorbell firmware to V2.2.60+. |
| Three beeps / "calling failed" on doorbell | In doorbell settings, ensure "Call Management Center" is NOT selected. |
| Cannot hear message clearly | Try a different voice in Piper config. Ensure ffmpeg transcode completed without errors. |
| MQTT connection refused | If your broker requires authentication, set `mqtt_username` and `mqtt_password`. |

## Files

```
repository.yaml              HA app repository manifest
sip_responder/
  config.yaml                App manifest, options, schema
  Dockerfile                 Container build
  run.sh                     Reads HA options, launches Python
  sip_responder.py           Main logic: SIP + MQTT + TTS
```
