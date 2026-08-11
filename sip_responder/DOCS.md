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
| TTS not generating | Check Piper add-on is installed and running |
| Doorbell not connecting | Verify `sip_domain` matches HA host IP. Check UDP 5060 firewall. |
| No audio on doorbell | Check UDP 4000-4001 firewall. Doorbell codec must be G.711 μ-law. |
| MQTT sensor not appearing | Reload MQTT integration. Check entity is enabled. |
| Too many log lines | Lower `log_level` to 1 or 2 |
