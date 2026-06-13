#!/bin/bash
# start_mac.sh — macOS/Linux launcher for FinAlly

# 1. Check for .env file
if [ ! -f .env ]; then
    echo "WARNING: .env file not found. Creating a default one from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
    else
        echo "OPENROUTER_API_KEY=your-key-here\nLLM_MOCK=true" > .env
    fi
fi

# 2. Check if Docker is running
echo "Checking if Docker is running..."
if ! docker info >/dev/null 2>&1; then
    echo "ERROR: Docker daemon is not running. Please start Docker and try again."
    exit 1
fi

# 3. Build and launch containers
echo "Building and starting FinAlly trading workstation..."
docker compose up -d --build

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to start Docker containers."
    exit 1
fi

# 4. Open in browser
echo "--------------------------------------------------------"
echo "FinAlly AI Workstation is running!"
echo "Access it at: http://localhost:8000"
echo "--------------------------------------------------------"

sleep 2
if command -v open >/dev/null 2>&1; then
    open "http://localhost:8000"
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:8000"
fi
