#!/bin/bash
# SIP Doorbell Responder — startup script

export SIP_USERNAME="$(bashio config 'sip_username')"
export SIP_PASSWORD="$(bashio config 'sip_password')"
export SIP_DISPLAY_NAME="$(bashio config 'sip_display_name')"
export SIP_DOMAIN="$(bashio config 'sip_domain')"
export SIP_PORT="$(bashio config 'sip_port')"
export RTP_PORT_START="$(bashio config 'rtp_port_start')"
export TTS_MESSAGE="$(bashio config 'tts_message')"
export TTS_WAV_PATH="$(bashio config 'tts_wav_path')"
export TTS_AUDIO_DURATION="$(bashio config 'tts_audio_duration')"
export HA_URL="$(bashio config 'ha_url')"
export HA_TOKEN="$(bashio config 'ha_token')"
export TTS_ENGINE="$(bashio config 'tts_engine')"
export MQTT_HOST="$(bashio config 'mqtt_host')"
export MQTT_PORT="$(bashio config 'mqtt_port')"
export MQTT_USERNAME="$(bashio config 'mqtt_username')"
export MQTT_PASSWORD="$(bashio config 'mqtt_password')"

echo "Starting SIP Doorbell Responder..."
exec python3 /sip_responder.py
