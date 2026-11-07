#!/bin/bash
# ---------------------------------------------------------------------------
# Footwear Warehouse AI - Desktop Double-Click Launch Shortcut (macOS)
# Double-click this file in Finder to automatically launch the Supervisor UI
# ---------------------------------------------------------------------------

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "👟 Footwear Warehouse AI — Supervisor Cockpit Launcher"
echo "=========================================================="

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed or not in your PATH."
    echo "Please install Python 3.9+ from https://www.python.org or via Homebrew."
    read -p "Press [Enter] to exit..."
    exit 1
fi

# Set up virtual environment if missing
if [ ! -d ".venv" ]; then
    echo "📦 Initializing virtual environment in .venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "⬇️  Installing project dependencies (this may take 1-2 minutes on first run)..."
    python -m pip install --upgrade pip
    if [ -f "requirements.txt" ]; then
        python -m pip install -r requirements.txt
    fi
    python -m pip install streamlit plotly pandas
else
    source .venv/bin/activate
fi

# Ensure streamlit is installed
if ! command -v streamlit &> /dev/null; then
    echo "⬇️  Installing Streamlit and essential packages..."
    pip install streamlit plotly pandas
fi

echo "🚀 Starting Streamlit Supervisor Dashboard on http://localhost:8501 ..."
streamlit run app/streamlit_app.py
