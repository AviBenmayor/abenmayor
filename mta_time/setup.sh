#!/bin/bash

echo "=========================================="
echo "MTA Train Time Display - Setup Script"
echo "=========================================="
echo ""

# Check if running on Raspberry Pi
if command -v raspi-config &> /dev/null; then
    echo "Raspberry Pi detected!"
    IS_PI=true
else
    echo "Running on non-Raspberry Pi system"
    IS_PI=false
fi

# Check for Node.js
if ! command -v node &> /dev/null; then
    echo "Node.js not found. Installing..."

    if [ "$IS_PI" = true ]; then
        curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        echo "Please install Node.js manually from https://nodejs.org"
        exit 1
    fi
else
    echo "Node.js found: $(node --version)"
fi

# Install dependencies
echo ""
echo "Installing npm dependencies..."
npm install

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo ""
    echo "Creating .env file..."
    cp .env.example .env
    echo ".env file created. You can add your MTA API key later if needed."
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Available commands:"
echo ""
echo "  npm start         - Run terminal display (auto-updates every 30s)"
echo "  npm run simple    - Run simple single-line display"
echo "  npm run web       - Run web server (access at http://localhost:3000)"
echo ""
echo "For hardware setup instructions, see HARDWARE.md"
echo ""

# Ask if user wants to test
read -p "Would you like to test the web display now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "Starting web server..."
    echo "Open http://localhost:3000 in your browser"
    echo "Press Ctrl+C to stop"
    echo ""
    npm run web
fi
