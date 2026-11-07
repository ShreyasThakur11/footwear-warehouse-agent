#!/bin/bash
# ---------------------------------------------------------------------------
# Footwear Warehouse AI — Unified Operations Launcher
# ---------------------------------------------------------------------------

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=========================================================="
echo "👟 FOOTWEAR WAREHOUSE AI — AGENTIC OPERATIONS PLATFORM"
echo "=========================================================="
echo ""
echo "Please select an option to launch:"
echo ""
echo "  [1] Launch Supervisor Cockpit (Streamlit Dashboard)"
echo "  [2] Open Interactive 2D Warehouse Simulator & Site (index.html)"
echo "  [3] Run Multi-Agent Daily Planning Cycle (LangGraph multi-agent)"
echo "  [4] Run Automated Unit & Integration Tests (pytest)"
echo "  [5] Rebuild / Install Python Virtual Environment (.venv)"
echo "  [6] Exit"
echo ""
read -p "Select [1-6] (default: 1): " choice
choice=${choice:-1}

# Function to ensure virtual environment is active
ensure_venv() {
    if [ ! -d ".venv" ]; then
        echo "Creating virtual environment in .venv..."
        python3 -m venv .venv
        source .venv/bin/activate
        echo "Installing core dependencies..."
        python -m pip install --upgrade pip
        if [ -f "requirements.txt" ]; then
            python -m pip install -r requirements.txt
        fi
        python -m pip install streamlit plotly pandas
    else
        source .venv/bin/activate
    fi
}

case "$choice" in
    1)
        ensure_venv
        echo "🚀 Launching Streamlit Supervisor Dashboard..."
        streamlit run app/streamlit_app.py
        ;;
    2)
        echo "🌐 Opening Interactive 2D Simulator in default browser..."
        if command -v open &> /dev/null; then
            open index.html
        elif command -v xdg-open &> /dev/null; then
            xdg-open index.html
        else
            python3 -m webbrowser index.html
        fi
        ;;
    3)
        ensure_venv
        echo "🤖 Executing LangGraph Multi-Agent Daily Cycle..."
        export PYTHONPATH="$DIR/src:$PYTHONPATH"
        python3 -c "
from warehouse_ai.agents.orchestrator import run_daily_cycle
import json

print('\n--- Starting Daily Operational Cycle ---')
plan = run_daily_cycle(target_date='2024-03-15', provider='mock', is_weekly=True)
print('\n✅ Cycle Completed Successfully!')
print(f'Status: {plan.governance_status}')
print(f'Notes: {plan.governance_notes}')
"
        ;;
    4)
        ensure_venv
        echo "🧪 Running Pytest Suite..."
        export PYTHONPATH="$DIR/src:$PYTHONPATH"
        pytest
        ;;
    5)
        echo "📦 Setting up clean Python virtualenv..."
        rm -rf .venv
        python3 -m venv .venv
        source .venv/bin/activate
        python -m pip install --upgrade pip
        pip install -e .
        echo "✅ Environment configured successfully."
        ;;
    6)
        echo "Goodbye!"
        exit 0
        ;;
    *)
        echo "Invalid selection. Exiting."
        exit 1
        ;;
esac

