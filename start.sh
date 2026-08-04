#!/bin/bash
# Starts the Armenian voice assistant: FastAPI backend (:8191) + Vite dev server (:5178).
set -e
cd "$(dirname "$0")"

if ! curl -s -o /dev/null http://localhost:11434/api/tags; then
  echo "Ollama doesn't seem to be running. Starting 'ollama serve' in the background..."
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 2
fi

./venv/bin/python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8191 --reload &
BACKEND_PID=$!
trap "kill $BACKEND_PID 2>/dev/null" EXIT

cd frontend
if [ ! -d node_modules ]; then
  npm install
fi
npm run dev
