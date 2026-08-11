# Changelog

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
