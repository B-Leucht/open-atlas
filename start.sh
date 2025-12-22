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
