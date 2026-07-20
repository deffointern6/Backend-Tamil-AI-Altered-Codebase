#!/bin/bash

# Configuration for local CPU constraints
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2

# Port mapping matching settings/config.py
declare -A PORT_MAP
PORT_MAP=(
    ["letter-gen"]=7860
    ["paraphrase-gen"]=7861
    ["mcq-gen"]=7862
    ["tongue-twister"]=7863
    ["poem-gen"]=7864
    ["email-gen"]=7865
    ["proofreader"]=7866
)

# Get script directory and setup paths
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BASE_DIR="$SCRIPT_DIR/../local_spaces"

# Load environment variables from .env if present to authenticate HF downloads
if [ -f "$SCRIPT_DIR/../.env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' "$SCRIPT_DIR/../.env" | xargs)
fi

# Find python command from venv or .venv
VENV_PYTHON=""
if [ -f "$SCRIPT_DIR/../venv/bin/python" ]; then
    VENV_PYTHON="$SCRIPT_DIR/../venv/bin/python"
elif [ -f "$SCRIPT_DIR/../.venv/bin/python" ]; then
    VENV_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
fi

# Determine python command
if [ -n "$VENV_PYTHON" ]; then
    PYTHON_CMD="$VENV_PYTHON"
    echo "Using virtual environment python: $PYTHON_CMD"
else
    PYTHON_CMD="python3"
    echo "Virtual environment not found. Falling back to system python: $PYTHON_CMD"
fi

# Start each app in the background
for name in "${!PORT_MAP[@]}"; do
    port=${PORT_MAP[$name]}
    dir="$BASE_DIR/$name"
    
    if [ -d "$dir" ]; then
        echo "Starting $name on port $port..."
        cd "$dir"
        
        # Run app.py in background, redirecting stdout/stderr to log files
        PORT=$port GRADIO_SERVER_PORT=$port GRADIO_SERVER_NAME="127.0.0.1" "$PYTHON_CMD" app.py > "$BASE_DIR/$name.log" 2>&1 &
        
        cd - > /dev/null
    else
        echo "Error: Space directory $dir not found. Please run download_spaces.py first."
    fi
done

echo "All local spaces launched in the background."
echo "View running processes: ps aux | grep app.py"
echo "View logs: tail -f local_spaces/*.log"
