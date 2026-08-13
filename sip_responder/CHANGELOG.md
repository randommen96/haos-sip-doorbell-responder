# Changelog

## 1.0.103

- TTS retry hardening: exceptions from an attempt (e.g. HTML error page
  from a restarting Supervisor proxy, non-UTF8 ffmpeg output) are now
  treated as failed attempts instead of killing the retry loop.
- Outbound announcements now have a 10-minute retry limit — stale
  messages are dropped instead of being played hours later, and retry
  threads no longer pile up during a long TTS outage. Startup TTS
  keeps retrying forever.

## 1.0.102

- Stale call watchdog: if the doorbell never answers our BYE (power
  cut / reboot mid-call), the call slot is released 30s after hangup
  so new rings are answered instead of getting 486 busy.
- Doorbell address re-learned on every ring — ISAPI outbound keeps
  working after a doorbell DHCP change without an add-on restart.
- Cleanup: removed dead onRegState callback, stale ALSA comment,
  README audio paths, DEVELOPMENT.md tree entry, test helper backport,
  and fixed the MQTT source label logic.

## 1.0.101

- RTP: reduced port range from two pairs to one (4000-4001). Verified the
  account transport is lazy and startup opens no RTP sockets — only the
  single active ring call ever uses a pair.

## 1.0.100

- Fix startup TTS temp-file leak: downloaded .audio file is now removed
  when the transcode fails (previously kept), and partial _ulaw.wav from
  a failed ffmpeg run is removed too.
- Drop redundant post-playback wait in the outbound worker: audio is
  fully streamed at real-time pace before play_audio_via_isapi returns.

## 1.0.99

- Cleanup: removed dead options (`sip_password`, `sip_display_name`,
  `doorbell_number`, `tts_audio_duration`) and the dead `ports` block
  (ignored under host networking).
- Fixed player teardown race: player explicitly destroyed before hangup
  instead of leaving it to GC (kills "Remove port failed PJ_EINVAL" and
  the ~30 EOF log lines after playback). Playback tail tightened.
- Set PJSIP conference clock rate to 8 kHz — all audio is PCMU, so the
  per-call 8k<->16k resampling no longer runs.
- Docker: /etc/asound.conf null device silences ~60 lines of ALSA card
  scan errors per startup and per call (visible at every log level).
- Docs: removed go2rtc references (ISAPI playback is direct), corrected
  sip_username guidance (`responder` is the identity the doorbell calls).

## 1.0.98

- Fixed ISAPI playback: doorbell ignores audio sent as PUT body.
  Now replicates go2rtc's proven flow — zero-length PUT audioData on
  keep-alive TCP connection, stream raw mu-law bytes on the connection
  at 8kHz pace, then close. Verified working against the doorbell.

## 1.0.97

- ISAPI: don't wait for audioData response — the doorbell streams audio
  but only responds when the connection closes. Audio sent in background
  thread, channel closed after playback duration.

## 1.0.96

- Fix ISAPI playback reliability: close-before-open (Hikvision channels
  get stuck) and real-time audio streaming in 100ms chunks instead of
  a single burst that overran the device buffer.

## 1.0.95

- Extract raw PCMU via ffmpeg (-f mulaw) for ISAPI playback. Avoids
  Python wave module's inability to read G.711 mu-law format tag.

## 1.0.94

- Fix ISAPI 401: use Digest authentication (Hikvision rejects Basic).

## 1.0.93

- Replaced embedded go2rtc with direct Hikvision ISAPI two-way audio
  playback. Simpler: 3 HTTP calls (discover channel, open, send audio,
  close) with basic auth. Our G.711 mu-law TTS output matches ISAPI
  natively. Removed go2rtc binary and config options.

## 1.0.92

- Fix NameError: restore go2rtc functions accidentally removed during
  outbound SIP cleanup. App crashed on startup with _start_go2rtc
  not defined.

## 1.0.91

- Removed SIP outbound mode entirely — go2rtc ISAPI is the only
  outbound audio path. Deleted OutboundCall, queue, busy handling.
- Renamed outbound_sip_uri to doorbell_ip (plain IP, auto-discovered).
- Removed doorbell_number option.
- Docs updated for go2rtc-only outbound audio.

## 1.0.90

- Major rework: removed SIP relay (200 lines) — PJSIP back on 5060.
- Outbound TTS now plays directly on the doorbell speaker via embedded
  go2rtc ISAPI backchannel (no SIP call needed). Enable with
  go2rtc_enabled + doorbell_admin_password.
- New options: go2rtc_enabled, doorbell_admin_username,
  doorbell_admin_password, go2rtc_port.
- Embedded go2rtc v1.9.14 binary (amd64/arm64).

## 1.0.89

- Fix Supervisor warnings: remove deprecated arch values (armhf, armv7,
  i386), remove invalid tmp:rw map entry. Only aarch64 and amd64.

## 1.0.88

- Add full relay forwarding log line to debug outbound INVITE path

## 1.0.87

- Critical fix: relay thread crashed on SIP responses (ValueError on
  '5060>'), permanently killing REGISTER handling and INVITE forwarding.
  Per-packet try/except keeps thread alive; doorbell address learned
  from REGISTER source; responses forwarded to doorbell as-is.

## 1.0.86

- Revert Record-Route header. Asterisk's create_out_of_dialog_request
  just calls pjsip_endpt_create_request — no Record-Route. Our INVITE
  from pjsua2 already matches Asterisk's exactly.

## 1.0.85

- Add Record-Route header to forwarded INVITEs matching Asterisk proxy
  behavior. Doorbell may require proxy-routed appearance for auto-answer.

## 1.0.84

- Restore relay-based SIP registrar approach. Indoor station XML
  registration (1.0.80–1.0.83) confirmed not supported on KB8113
  outdoor station (403 Forbidden). Relay handles REGISTER 401/200 OK
  and forwards INVITEs from port 5060 with Via/Contact rewriting.

## 1.0.79

- Rewrite Via sent-by in outbound INVITEs to port 5060 so the doorbell
  sees the INVITE as coming through its registered SIP server.

## 1.0.78

- Add full hex dump of forwarded INVITE to verify relay rewriting

## 1.0.77

- Fix missing \r\n on To header in REGISTER response f-string.
  The original code never had it; the tag fix accidentally compensated
  by adding \r\n to the tag string. When cleaned up, To merged with
  Call-ID on the same line, breaking YATE's parser.

## 1.0.76

- Fix double \r\n in Via/To headers that broke SIP message parsing.
  Via rport fix was adding \r\n to a string that already gets \r\n
  in the f-string, creating an empty line after Via. YATE couldn't
  parse the response — To, Call-ID, Contact, Expires became body text.

## 1.0.75

- Set received/rport in Via header of REGISTER responses per RFC 3581

## 1.0.74

- Add hex dump of REGISTER 200 OK for byte-level comparison with Asterisk
- Remove 100 Trying (didn't affect YATE transaction state matching)

## 1.0.73

- Send 100 Trying before REGISTER 200 OK: YATE requires provisional
  response to transition transaction to Process state before accepting
  the final response. Matches Asterisk's PJSIP transaction behavior.

## 1.0.72

- Remove debug log truncation to see full REGISTER 200 OK response

## 1.0.71

- Strip display name from Contact in REGISTER 200 OK (matches Asterisk behavior)
- Add debug logging for full 200 OK response content
- Research: YATE source confirms m_resend = expires * 750ms + now;
  re-registration at 75% of expire interval means doorbell doesn't accept our 200 OK

## 1.0.70

- Match Asterisk's REGISTER handling exactly: add opaque param to
  WWW-Authenticate, set To tag to Via branch (not removed, not custom).
  Nonce format now ts/md5hash matching Asterisk's build_nonce().

## 1.0.69

- Fix WWW-Authenticate: add qop="auth" and proper random nonce matching
  Asterisk's format. Missing qop likely caused doorbell to ignore 401.

## 1.0.68

- Fix INVITE loop: outbound relay forwarding no longer waits for and
  forwards responses, preventing infinite INVITE→500→retry cycle.

## 1.0.67

- Fix relay: route outbound through SIP_DOMAIN (not 127.0.0.1) so relay
  actually receives INVITEs on the bound interface.
- Don't add tag to To header in REGISTER 200 OK.

## 1.0.66

- Fix relay forwarding: match on port (5061) not address — PJSIP sends
  from real interface IP, not 127.0.0.1. Outbound INVITEs now forwarded.
- Add Expires header to REGISTER 200 OK, parsed from doorbell request.
  Reduced outbound call timeout to 15s.

## 1.0.65

- Fix relay outbound forwarding: rewrite Contact and Via 127.0.0.1
  addresses to LAN IP so doorbell can route back. Added diagnostic
  log for outbound forwarding.

## 1.0.64

- Relay V2: proper REGISTER 200 OK with Contact header and expires,
  outbound INVITEs routed through relay for correct source port (5060).
  Doorbell should now show "Registered" and accept incoming calls.

## 1.0.63

- Remove registrar relay and outbound proxy: py3-pjsua bindings lack both
  `pjsip_registrar_create` and `proxyConfig`. Back to PJSIP on 5060.

## 1.0.62

- Route outbound SIP through relay (proxy) so INVITEs appear from
  port 5060 where the doorbell registered, not PJSIP's port 5061.
- Relay now handles bidirectional forwarding and outbound proxy.

## 1.0.61

- Fix registrar relay: bind UDP socket synchronously in main thread
  before PJSIP starts, eliminating race where PJSIP could grab the
  port first. Socket passed to daemon thread after binding.

## 1.0.60

- Add UDP registrar relay on SIP port: intercepts REGISTER, responds
  200 OK directly. Forwards all other SIP traffic to PJSIP on port+1.
  PJSIP's registrar module not available in Alpine py3-pjsua package.
- PJSIP now listens on 5061; relay on 5060 handles both REGISTER and
  call forwarding transparently. No doorbell config changes needed.

## 1.0.59

- Add PJSIP registrar module via ctypes: responds 200 OK to doorbell
  REGISTER requests. The registrar is in libpjsip-simple which is always
  installed alongside py3-pjsua. If loading fails, logs a warning and
  continues (REGISTER will be dropped, same as before).

## 1.0.57

- Rename default `sip_username` from `doorbell` to `responder` — fixes
  identity collision where outbound INVITE From header matched the
  doorbell's own identity. Two distinct identities now.
- Add `doorbell_number` option (default `doorbell`) — the doorbell's
  SIP identity for outbound calls. Clear separation from `sip_username`.
- Startup log now shows both identities.
- Set session timer values (90/3600) to pass PJSIP assertions while
  keeping re-INVITEs out of normal short TTS calls.

## 1.0.56

- Remove session timer config entirely: PJSIP defaults have them disabled.
  Sequential assertion failures (min_se, then sess_expires >= min_se)
  confirmed the config approach is wrong — just don't configure them.

## 1.0.55

- Fix session timer assertion: PJSIP requires `Min-SE >= 90` per RFC 4028.
  Setting it to 0 caused `Assert failed: setting->min_se >= 90`. Set to 90.

- Remove session timer config entirely: PJSIP defaults have them disabled.
  Sequential assertion failures (min_se, then sess_expires >= min_se)
  confirmed the config approach is wrong — just don't configure them.

## 1.0.54

- Switch to host networking: PJSIP now binds to the real LAN IP instead
  of Docker bridge. Fixes outbound INVITEs advertising unreachable
  172.30.x.x addresses in Via, Contact, and SDP.
- Disable SIP session timers: the KB8113's YATE stack has broken
  re-INVITE handling (known 32-second drop issue).
- Removed `publicAddr` workarounds — not mapped in py3-pjsua SWIG bindings.

## 1.0.53

- Set `publicAddr` on both SIP and media transport configs to `sip_domain`
  so outbound INVITEs advertise the HA host's LAN IP everywhere (Via,
  Contact, SDP) instead of the unreachable Docker bridge IP.

## 1.0.52

- Set `publicAddr` to `sip_domain` on media transport config so outbound
  INVITEs advertise the HA host's LAN IP in SDP and Contact headers.

## 1.0.51

- Fix RTP port exhaustion on outbound calls: `portRange` increased from
  1 to 2, giving the outbound call its own RTP/RTCP port pair (4002-4003).
  The account reserves 4000-4001; mutual exclusion ensures no further
  collisions.

## 1.0.50

- Fix auto-discovery: use `remoteContact` (Contact header) instead of
  `remoteUri` (From header). The From header carries the doorbell's SIP
  identity with our domain — useless for calling back. The Contact header
  has the doorbell's actual reachable IP.

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
