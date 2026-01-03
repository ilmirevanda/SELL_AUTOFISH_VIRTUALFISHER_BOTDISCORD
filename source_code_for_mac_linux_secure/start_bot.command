#!/bin/bash
cd "$(dirname "$0")"
echo "Starting AutoFishBot..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed."
    echo "Please install Python 3.12 from https://www.python.org/downloads/"
    read -p "Press Enter to exit..."
    exit 1
fi

# Run the bot
python3 loader.py

# Keep terminal open if bot crashes
echo "Bot stopped."
read -p "Press Enter to exit..."
