#!/bin/bash

echo "Starting Munich City Data Search Application"
echo "============================================"
echo ""

# Cleanup function to kill backend when script exits
cleanup() {
    echo ""
    echo "Shutting down..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo "Backend stopped"
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check and setup backend dependencies
echo "Checking backend dependencies..."
cd backend || exit 1

# Detect which virtual environment to use
# Prefer .venv (uv default) if it exists, otherwise use venv
if [ -d ".venv" ]; then
    VENV_DIR=".venv"
elif [ -d "venv" ]; then
    VENV_DIR="venv"
else
    VENV_DIR=""
fi

# Check if uv is available
if command -v uv &> /dev/null; then
    HAS_UV=1
else
    HAS_UV=0
fi

# Create venv if it doesn't exist
if [ -z "$VENV_DIR" ]; then
    if [ $HAS_UV -eq 1 ]; then
        echo "Creating Python virtual environment with uv..."
        uv venv
        VENV_DIR=".venv"
    else
        echo "Creating Python virtual environment with venv..."
        python3 -m venv venv
        VENV_DIR="venv"
    fi
fi

echo "Using virtual environment: $VENV_DIR"

# Activate the virtual environment
source "$VENV_DIR/bin/activate"

# Install/update Python dependencies
if [ $HAS_UV -eq 1 ]; then
    echo "Installing Python dependencies with uv..."
    uv pip install -r requirements.txt
else
    echo "Installing Python dependencies with pip..."
    pip install -r requirements.txt
fi

# Source the .env file if it exists (for API keys)
if [ -f ".env" ]; then
    echo "Loading environment from .env..."
    source .env
fi

cd ..

# Check and setup frontend dependencies
echo "Checking frontend dependencies..."
cd frontend

if [ ! -d "node_modules" ]; then
    echo "Installing npm dependencies..."
    npm install
else
    # Check if package.json is newer than node_modules
    if [ "package.json" -nt "node_modules" ]; then
        echo "Updating npm dependencies..."
        npm install
    fi
fi

cd ..

echo ""

# Check if backend is running
if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "✓ Backend is already running on port 5001"
else
    echo "Starting backend server..."
    cd backend

    # Activate venv and set environment for development
    source "$VENV_DIR/bin/activate"
    if [ -f ".env" ]; then
        source .env
    fi
    export ENV=development

    python3 main.py &
    BACKEND_PID=$!
    cd ..

    # Wait for backend to be ready
    echo "Waiting for backend to start..."
    for i in {1..30}; do
        if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
            echo "✓ Backend started (PID: $BACKEND_PID)"
            break
        fi
        sleep 0.5
    done

    # Check if backend failed to start
    if ! lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "✗ Backend failed to start. Check the logs above for errors."
        exit 1
    fi
fi

echo ""
echo "Starting frontend server..."
echo "The React app will open in your browser at http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

cd frontend
npm start