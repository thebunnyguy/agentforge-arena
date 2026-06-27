#!/bin/bash
# Double-click this file in Finder to start AgentForge Arena.
# It launches the local app (UI + API + worker) and opens your browser.
cd "$(dirname "$0")" || exit 1
exec python3 afa_app.py
