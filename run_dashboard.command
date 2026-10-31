#!/bin/bash
# ---------------------------------------------------------------------------
# Footwear Warehouse AI - Desktop Launch Shortcut
# Double-click this script from Finder or Desktop to start the supervisor UI
# ---------------------------------------------------------------------------

set -e

# Change directory to the repository root
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "👟 Launching Footwear Warehouse AI Operations Cockpit..."
echo "=========================================================="

if [ -f ".venv/bin/activate" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
fi

echo "Opening Streamlit Supervisor Dashboard on http://localhost:8501 ..."
streamlit run app/streamlit_app.py

