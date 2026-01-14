#!/bin/bash
# Demo startup script for poster session (ngrok version)

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "Starting Open Atlas Demo..."

# Kill any existing processes
lsof -ti:3000 | xargs kill -9 2>/dev/null
lsof -ti:5001 | xargs kill -9 2>/dev/null
pkill -f ngrok 2>/dev/null

# Start backend
echo "Starting backend..."
(cd "$ROOT/backend" && ./.venv/bin/python app.py) &
BACKEND_PID=$!
sleep 2

# Start frontend
echo "Starting frontend..."
(cd "$ROOT/frontend" && npm start) &
FRONTEND_PID=$!

echo "Waiting for frontend to start..."
sleep 12

# Start ngrok
echo "Starting ngrok tunnel..."
ngrok http 3000 > /dev/null &
NGROK_PID=$!
sleep 4

# Get ngrok URL
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"https://[^"]*' | cut -d'"' -f4)

echo ""
echo "============================================"
echo "Demo is ready!"
echo ""
echo "Public URL: $NGROK_URL"
echo ""
echo "Opening QR code in browser..."
echo "============================================"

# Open QR code
open "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=$NGROK_URL"

trap "kill $BACKEND_PID $FRONTEND_PID $NGROK_PID 2>/dev/null; pkill -f ngrok; exit" SIGINT SIGTERM
wait
