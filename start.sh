#!/bin/bash
echo "========================================="
echo "   AZIM AI TRADER v3 - Starting..."
echo "========================================="
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python3 nahi mila!"
    exit 1
fi

# Install requirements
echo "[1/3] Dependencies install ho rahi hain..."
pip3 install -r requirements.txt --quiet

echo "[2/3] Bot start ho raha hai..."
echo ""
echo "Dashboard: http://localhost:8000"
echo ""
echo "[3/3] Logs:"
echo "========================================="

python3 app.py
