# Changelog

## 1.0.49

- Fix stale defaults in DOCS.md and README.md: `mqtt_listen_topic` and
  `outbound_sip_uri` descriptions now match actual code defaults and
  auto-discovery behavior.

## 1.0.48

- Default `mqtt_listen_topic` to `"doorbell/announce"` instead of empty.
- Auto-discover doorbell SIP URI from first incoming call's `remoteUri` —
  no need to manually configure `outbound_sip_uri` for the common case.

## 1.0.47

- Refactor outbound call state: replace 5 separate `global` variables with
  a single `_outbound` dict. No `global` declarations needed — cleaner and
  eliminates the class of scoping bugs fixed in 1.0.45/1.0.46.

## 1.0.46

- Fix UnboundLocalError in `process_outbound_requests`: `_outbound_active`
  and `_outbound_call_id` were assigned without `global` declaration,
  causing Python to treat them as unbound locals on first read.

## 1.0.45

- Fix NameError: `mqtt_client.on_message` referenced `_on_mqtt_message` before
  it was defined, crashing the app at import. Moved assignment after definition.

## 1.0.44

- MQTT-triggered outbound calls: listen on a configurable topic, generate
  TTS from the payload, call the doorbell, play the message, hang up.
  Configurable via `mqtt_listen_topic` and `outbound_sip_uri`.
- TTS retry with exponential backoff at startup (5s -> 300s cap).
  Covers Piper warm-up, HA API routing delays, and transient failures.
  Configurable via `tts_retry_enabled`, `tts_retry_max_attempts`,
  `tts_retry_initial_delay`, and `tts_retry_max_delay`.
- Refactored audio playback into shared `play_audio_in_call()` for
  incoming and outbound calls. `OutboundCall` class with same GC fix.
- Mutual exclusion: incoming calls rejected with 486 Busy during
  outbound calls. MQTT triggers queued with latest-message-wins.
- Thread-safe design: MQTT callbacks only enqueue jobs via queue.Queue;
  all pjsua2 operations stay on the main thread.

## 1.0.43

- Increased pre-playback delay to 200ms for reliable audio start on all
  calls. Prevents first syllables being lost on short messages.
- Documented relay click fix: set I/O Output to Electric Lock mode.

## 1.0.42

- Increased pre-playback delay to 100ms (from 50ms) for reliable
  conference port linking. Fixes occasional cut-off on short messages.
- Reverted silence pad approach — waiting is cleaner than modifying audio.

## 1.0.41

- Added timestamps to all log output (HH:MM:SS prefix).
- Replaced time.sleep() with libHandleEvents() loop during playback.

## 1.0.40

- Fixed short TTS messages: process events during playback so conference
  ports connect immediately instead of blocking on time.sleep().

## 1.0.39

- Added tests: audio transcode, TTS URL parsing, MQTT discovery payload
  format, audio duration calculation (7 tests total).
- Added DEVELOPMENT.md with project structure, build/test/release docs.
- Removed outdated plan.MD (predates current implementation).
- CI now includes ffmpeg for transcode tests.

## 1.0.38

- Removed duplicate "Hung up after playback" log line.

## 1.0.37

- Removed self-registration. The GC fix (1.0.20) was the real solution
  to 603 Decline, not the self-registration. Eliminates 408 timeout noise.

## 1.0.36

- Silenced 408 registration timeout log (normal when no registrar module).

## 1.0.35

- Improved bell-shaped icon with gold clapper.
- Default log_level lowered from 2 to 1 (ERROR) for quieter startup.

## 1.0.34

- Fixed OPTIONS_PATH import after extracting config.py module.

## 1.0.33

- Added in-app documentation (DOCS.md) with full option reference,
  log level table, doorbell setup, automations, and troubleshooting.
- Added `url` and `documentation` links to config.yaml for HA UI.
- Documented log levels in README with usage guidance.

## 1.0.32

- Added configurable `log_level` option (0-5, default 2). Reduces PJSIP
  detail logs at WARNING level. Set to 5 for verbose debugging.
- Added `icon.png` for add-on store listing.
- Added CI workflow: verifies changelog entry for current version, runs
  unit tests for config loading.
- Added basic unit tests for `load_options()`.

## 1.0.31

- Fixed `sensor_name` option not being read from HA config (was missing
  from Python defaults, silently filtered).
- Updated changelog covering all previous versions.

## 1.0.30

- Fixed MQTT authentication: added `services: ["mqtt:want"]` so the
  Supervisor auto-provides broker credentials. No manual MQTT config.
- Improved MQTT diagnostics: clear log messages for connection status,
  auth failures, and Supervisor service discovery.

## 1.0.29

- Works end-to-end: SIP call answering, TTS playback, MQTT sensor.

## 1.0.23

- Fixed audio looping: `PJMEDIA_FILE_NO_LOOP` plays message once,
  duration calculated from file size instead of config.
- Restored `setNullDev()` — the 603 auto-reject was caused by Python
  garbage collection, not the null audio device.

## 1.0.22

- Fixed garbage collection bug: Call objects created in `onIncomingCall`
  were freed by Python GC, causing PJSIP to auto-reject with 603.
- Fixed `getInfo()` typo (was `info()`).
- Set `threadCnt=0` for Python callback dispatch.
- Added `onIncomingCall` handler to route INVITEs to custom Call class.

## 1.0.14

- Removed SIP registration: pjsua2 has no registrar module. App now
  accepts INVITEs addressed to `sip_username` without registration.

## 1.0.13

- Initial working SIP endpoint (passive listen mode).

## 1.0.12

- Auto-discover HA built-in MQTT broker via Supervisor API.
- Leave `mqtt_host` empty to use the built-in broker.

## 1.0.11

- Added `tts_voice` option for custom Piper voice/language.

## 1.0.10

- Fixed ffmpeg transcode: Piper returns MP3, output WAV with mu-law.

## 1.0.9

- Fixed TTS audio download URL: handle absolute URLs from HA with
  external_url configured. Always route through Supervisor proxy.

## 1.0.7

- Replaced user-created `ha_token` with auto-injected `SUPERVISOR_TOKEN`.
  Added `homeassistant_api: true` — no manual token setup needed.

## 1.0.6

- Moved CHANGELOG.md into app directory (where Supervisor expects it).

## 1.0.5

- Added changelog, suppressed ALSA/JACK noise, fixed Python log buffering,
  clearer SIP registration and config summary logging.

## 1.0.4

- Fixed s6-overlay compatibility: `init: false` and `with-contenv bashio`.
- App config read from `/data/options.json`, Python import path fixed.
- Added MQTT authentication options.

## 1.0.3

- Removed bashio CLI dependency. Simplified run.sh.

## 1.0.2

- Added `init: false` to bypass s6-overlay init conflict.
- Added MQTT username/password config.

## 1.0.1

- Initial working version: Piper TTS, SIP endpoint, MQTT discovery.

## 1.0.0

- Initial release.
