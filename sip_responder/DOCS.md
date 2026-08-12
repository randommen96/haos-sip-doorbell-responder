# SIP Doorbell Responder

Answers SIP calls from a Hikvision KB8113-IME1 doorbell and plays a text-to-speech message via Piper TTS.

## How It Works

1. At startup, the app generates a TTS audio file via HA's Piper add-on and caches it
2. When the doorbell button is pressed, it sends a SIP INVITE to the app
3. The app answers the call, plays the TTS message, hangs up
4. Doorbell state (ON/OFF) is published via MQTT for HA automations

## Configuration

### Required

| Option | Description |
|---|---|
| `sip_domain` | Your HA host IP address (e.g., `10.26.5.254`). The doorbell connects to this. |
| `sip_username` | SIP username. Must match the doorbell's Register User Name. |
| `sip_password` | SIP password. Must match the doorbell's Registration Password. |

### Optional

| Option | Default | Description |
|---|---|---|
| `tts_message` | `"Please use the other bell."` | Text spoken by the doorbell |
| `tts_voice` | `""` | Piper voice name (e.g., `en_US-lessac-medium`). Empty = Piper default. |
| `tts_engine` | `tts.piper` | TTS entity to use |
| `tts_audio_duration` | `5` | Fallback duration if file size can't be read |
| `sensor_name` | `"Doorbell Pressed"` | Name of the MQTT binary sensor in HA |
| `log_level` | `1` | PJSIP log level: 0=fatal, 1=error (default), 2=warning, 3=info, 4=debug, 5=trace |
| `mqtt_host` | `""` | MQTT broker host. Leave empty for auto-discovery. |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_username` | `""` | MQTT username. Leave empty for auto-discovery. |
| `mqtt_password` | `""` | MQTT password. Leave empty for auto-discovery. |
| `sip_port` | `5060` | SIP signalling port |
| `rtp_port_start` | `4000` | First RTP port (uses this + next for audio) |
| `sip_display_name` | `"Doorbell Responder"` | Display name in SIP messages |
| `tts_wav_path` | `"/media/tts/doorbell_message.wav"` | Static WAV fallback if API unavailable |
| `mqtt_listen_topic` | `"doorbell/announce"` | MQTT topic for outbound call triggers (empty = disabled) |
| `outbound_sip_uri` | `""` | SIP URI to call. Auto-discovered from first ring if empty. |
| `tts_retry_enabled` | `true` | Retry TTS with backoff on failure |
| `tts_retry_max_attempts` | `0` | Max retries (0 = infinite) |
| `tts_retry_initial_delay` | `5` | Seconds before first retry |
| `tts_retry_max_delay` | `300` | Max seconds between retries |

### Log Levels

At the default level of 1 (ERROR), PJSIP startup is nearly silent. Only actual errors appear.

| Level | Shows |
|---|---|
| 0 | Fatal errors only |
| 1 | Errors |
| 2 | Warnings (default — quiet startup) |
| 3 | Info (module registration, transport setup) |
| 4 | Debug (detailed call flow) |
| 5 | Trace (every SIP message including REGISTER retries) |

Set `log_level` to 5 only when debugging SIP issues.

## MQTT-Triggered Outbound Calls

The app can make outbound SIP calls to the doorbell (or any SIP endpoint), triggered by MQTT messages. This enables automations to make the doorbell speak arbitrary messages.

### How It Works

1. You publish a message to the configured `mqtt_listen_topic` (e.g., `doorbell/announce`)
2. The app generates TTS audio from the message payload
3. The app places an outbound SIP call to `outbound_sip_uri`
4. The doorbell auto-answers, the TTS message plays, and the call hangs up

### Setup

1. `mqtt_listen_topic` defaults to `doorbell/announce` — set to `""` to disable
2. `outbound_sip_uri` is optional — the doorbell's SIP address is auto-discovered
   on the first ring. Only set it explicitly if you need a different target.
3. The doorbell auto-answers by default when it receives a SIP call — no extra configuration needed

### Example Automation

```yaml
alias: "Announce package delivery"
trigger:
  - platform: state
    entity_id: binary_sensor.package_delivered
    to: "on"
action:
  - service: mqtt.publish
    data:
      topic: doorbell/announce
      payload: "A package has been delivered. Please collect it at the front door."
```

### Notes

- Outbound calls are skipped if the line is busy (incoming call in progress)
- TTS is generated on-demand with the same retry/backoff as startup TTS
- The `outbound_sip_uri` accepts bare IPs (`192.168.1.50`) — `sip:` is auto-prepended
- Retained MQTT messages are ignored to prevent stale triggers on restart

## Doorbell Setup

1. Go to **Configuration → Network → Basic Settings → SIP**
2. Enable VOIP Gateway
3. Set Server Address to your HA host IP, port 5060
4. Set Register User Name and Number to match `sip_username`
5. Go to **Intercom → Number Settings → Add**
6. Create a room (e.g., Room 1) with SIP Number matching `sip_username`
7. Go to **Intercom → Press Button to Call**
8. Select "Call Specified Indoor Station" → the room you created

The doorbell does not need to show "Registered" — it sends INVITE on button press regardless.

## HA Automations

The app creates `binary_sensor.doorbell_pressed` via MQTT discovery. Example automation:

```yaml
alias: "Doorbell Notification"
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

## Troubleshooting

| Symptom | Fix |
|---|---|
| TTS not generating | Check Piper add-on is installed and running. The app retries with backoff at startup — wait for "TTS ready" in logs. |
| Doorbell not connecting | Verify `sip_domain` matches HA host IP. Check UDP 5060 firewall. |
| No audio on doorbell | Check UDP 4000-4001 firewall. Doorbell codec must be G.711 μ-law. |
| MQTT sensor not appearing | Reload MQTT integration. Check entity is enabled. |
| Too many log lines | Lower `log_level` to 1 or 2 |
