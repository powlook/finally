#!/bin/bash
# stop_mac.sh — macOS/Linux script to stop FinAlly

echo "Stopping FinAlly workstation..."
docker compose down

if [ $? -eq 0 ]; then
    echo "FinAlly stopped successfully."
else
    echo "ERROR: Failed to stop FinAlly containers."
    exit 1
fi
