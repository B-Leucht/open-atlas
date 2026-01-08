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
cd backend

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate

# Install/update Python dependencies (prefer uv, fall back to pip)
if command -v uv &> /dev/null; then
    echo "Installing Python dependencies with uv..."
    uv pip install -r requirements.txt --quiet
else
    echo "Installing Python dependencies with pip..."
    pip install -r requirements.txt --quiet
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
if lsof -Pi :5001 -sTCP:LISTEN -t >/dev/null ; then
    echo "✓ Backend is already running on port 5001"
else
    echo "Starting backend server..."
    cd backend
    source venv/bin/activate
    python3 app.py &
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
fi

echo ""
echo "Starting frontend server..."
echo "The React app will open in your browser at http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

cd frontend
npm start
