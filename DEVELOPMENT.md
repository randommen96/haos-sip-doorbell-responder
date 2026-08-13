# Development

## Project Structure

```
.
├── .github/workflows/ci.yaml    CI: changelog check + tests
├── repository.yaml               HA add-on repository manifest
├── README.md                     User-facing docs
├── DEVELOPMENT.md                This file
├── sip_responder/
│   ├── config.yaml               Add-on manifest, options, schema
│   ├── Dockerfile                Container build
│   ├── config.py                 Config loader (no external deps)
│   ├── sip_responder.py          Main app: SIP, MQTT, TTS
│   ├── run.sh                    Entry point (bashio)
│   ├── icon.png                  Add-on store icon
│   ├── DOCS.md                   In-app documentation
│   └── CHANGELOG.md              Version history
└── tests/
    └── test_config.py            Unit tests for config loading
```

## Building Locally

```bash
# Build Docker image
docker build -t sip-test -f sip_responder/Dockerfile sip_responder/

# Run locally (will show config fallback since /data/options.json doesn't exist)
docker run --rm sip-test

# Run with mock config
docker run --rm -v /path/to/options.json:/data/options.json sip-test
```

## Running Tests

```bash
python3 -m pytest tests/ -v
```

## Releasing

1. Make changes
2. Bump `version` in `sip_responder/config.yaml`
3. Add entry to `sip_responder/CHANGELOG.md` under `## <version>` — keep descending (newest first)
4. Commit and push to `main`
5. In HA: Add-on Store → Check for updates → Update

## Key Design Decisions

- **SIP**: pjsua2 Python bindings via Alpine `py3-pjsua` package. No pip compilation.
- **TTS**: Piper via HA's internal API (Supervisor proxy + auto-injected token). No user token needed.
- **MQTT**: Auto-discovered via Supervisor services API (`mqtt:want`). No manual config needed.
- **Audio**: ffmpeg transcodes Piper output (MP3) to G.711 μ-law WAV for the doorbell's PCMU codec.
- **Call handling**: GC fix (_active_calls dict) prevents 603 Decline. No registration needed.

## Known Issues

- JACK probe noise (~5 lines at startup): PortAudio probes the JACK host API even with
  JACK_NO_START_SERVER. Not suppressible without rebuilding PortAudio. Harmless.
- SIP REGISTER from doorbell dropped: pjsua2 has no registrar module. Doorbell sends INVITE regardless.
- ALSA noise (fixed in 1.0.99): ~60 card-scan error lines per startup/call, silenced by
  mapping every PCM name in PortAudio's fallback list to null in /etc/asound.conf
  (overriding only `default` is not enough).
