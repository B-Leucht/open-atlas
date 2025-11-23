#!/bin/bash

echo "Starting Munich City Data Search Application"
echo "============================================"
echo ""

# Check if backend is running
if lsof -Pi :5000 -sTCP:LISTEN -t >/dev/null ; then
    echo "✓ Backend is already running on port 5000"
else
    echo "Starting backend server..."
    cd backend
    python3 app.py &
    BACKEND_PID=$!
    echo "✓ Backend started (PID: $BACKEND_PID)"
    cd ..
fi

echo ""
echo "Starting frontend server..."
echo "The React app will open in your browser at http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers"
echo ""

cd frontend
npm start
