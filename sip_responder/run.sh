#!/usr/bin/with-contenv bashio
# SUPERVISOR_TOKEN is injected automatically by the Supervisor.
# The add-on uses it to call HA Core API via http://supervisor/core/api/
exec python3 /sip_responder.py
