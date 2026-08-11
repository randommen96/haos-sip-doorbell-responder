# Changelog

## 1.0.12

- Auto-discover HA's built-in MQTT broker via Supervisor services API.
  Leave `mqtt_host` empty to use the built-in broker — no manual MQTT
  config needed. Same pattern as `homeassistant_api` for the HA token.

## 1.0.11

- Added `tts_voice` option to select a custom Piper voice/language.
  Leave empty to use Piper's default. Examples: en_US-lessac-medium,
  nl_NL-mls-medium, de_DE-thorsten-high, etc.

## 1.0.10

- Fixed ffmpeg transcode: Piper returns MP3 audio, not WAV. Output to
  proper WAV container with mu-law codec (not raw .ulaw format which
  ffmpeg doesn't recognize). Transcode works regardless of input format.
- Renamed cached file to `.wav` extension for PJSIP compatibility.

## 1.0.9

- Fixed TTS audio download: handle absolute URLs from HA (external_url
  config) by extracting path with urlparse, always route via Supervisor
  proxy where SUPERVISOR_TOKEN is valid.
- Added verbose logging for TTS generation and audio download.

## 1.0.8

- Removed ctypes ALSA error handler (segfault on some platforms).
- ALSA noise (~60 startup lines) is cosmetic; a crash is worse.
- Added SUPERVISOR_TOKEN as query param to audio download requests.

## 1.0.7

- Eliminated ALSA/PulseAudio/JACK startup noise (0 lines now).
  Uses ctypes `snd_lib_error_set_handler` with a custom no-op callback.
- Improved TTS API error diagnostics (shows HTTP status + response body)
- Removed unnecessary `/etc/asound.conf` from Docker image

## 1.0.6

- Replaced user-created `ha_token` with auto-injected `SUPERVISOR_TOKEN`
- TTS API calls now use internal Supervisor proxy (`http://supervisor/core/api/`)
- Added `homeassistant_api: true` to app config — no user token needed
- Removed `ha_url` and `ha_token` from user options (simplified setup)
- Moved CHANGELOG.md into app directory (where Supervisor expects it)

## 1.0.5

- Added CHANGELOG.md for HA Supervisor update notes
- Suppressed ALSA/PulseAudio/JACK device scan noise at startup
- Fixed Python log buffering (logs now appear in real time in HA)
- Clearer SIP registration status and config summary at startup

## 1.0.4

- Fixed s6-overlay compatibility with correct `with-contenv bashio` shebang
- App configuration now read directly from `/data/options.json` (no env-var dependency)
- Fixed Python import path for apk-installed packages (`.pth` file in site-packages)
- Added MQTT authentication support (`mqtt_username`, `mqtt_password` options)

## 1.0.3

- Removed bashio CLI dependency (bashio has no `config` subcommand)
- Simplified run.sh to `exec python3` with direct options.json reading
- Added `PYTHONPATH` fix for pjsua2 import

## 1.0.2

- Added `init: false` to bypass s6-overlay init conflict
- Added MQTT username/password configuration options
- Switched add-on terminology to "app" in documentation

## 1.0.1

- Fixed s6-overlay suexec PID 1 error
- Initial working version with Piper TTS integration
- SIP endpoint for Hikvision KB8113 doorbell
- MQTT binary sensor discovery for Home Assistant automations

## 1.0.0

- Initial release
