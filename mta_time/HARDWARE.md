# Hardware Setup Guide

## Recommended Hardware Options

### Option 1: Simple Desktop Display (Easiest)

**What You Need:**
- Raspberry Pi 4 (2GB or 4GB) - $45-55
- MicroSD card (32GB) - $8
- Power supply (USB-C, 3A) - $8
- HDMI cable - $5
- Any HDMI monitor or TV you already have
- **Total: ~$65 + monitor**

**Pros:**
- Easiest to set up
- Use any display you have
- Can be large and visible from distance
- Easy to debug

**Setup Time:** 30 minutes

---

### Option 2: Dedicated Small Display (Recommended)

**What You Need:**
- Raspberry Pi 4 (2GB) - $45
- 7" Touchscreen Display - $60-80
- MicroSD card (32GB) - $8
- Power supply - $8
- Case for display - $15
- **Total: ~$135-155**

**Pros:**
- Compact and dedicated
- Touch capability (for future features)
- Professional looking
- Can be wall-mounted

**Setup Time:** 1 hour

**Recommended Products:**
- Official Raspberry Pi 7" Touchscreen
- SmartiPi Touch 2 Case
- Waveshare 7" HDMI LCD

---

### Option 3: E-Ink Display (Most Professional)

**What You Need:**
- Raspberry Pi Zero 2 W - $15
- Waveshare 2.13" or 2.9" e-Paper HAT - $15-25
- MicroSD card (16GB) - $6
- Power supply (Micro USB) - $6
- Case - $10
- **Total: ~$50-60**

**Pros:**
- Very low power consumption
- Visible in bright light
- No backlight (easy on eyes)
- Professional appearance
- Battery powered option possible

**Cons:**
- Requires additional coding for display
- Slower refresh rate
- Black and white only

**Setup Time:** 2-3 hours

**Note:** Requires modifications to use e-ink library (not included in base code)

---

### Option 4: LED Matrix Display (Fun)

**What You Need:**
- Raspberry Pi Zero W - $10
- 64x32 RGB LED Matrix Panel - $25-40
- RGB Matrix HAT - $15
- Power supply (5V 4A) - $10
- **Total: ~$60-75**

**Pros:**
- Bright and eye-catching
- Retro aesthetic
- Visible from distance
- Great for dark rooms

**Cons:**
- Requires additional library setup
- Higher power consumption
- Can be bright at night

**Setup Time:** 2-3 hours

**Recommended Products:**
- Adafruit RGB Matrix HAT
- 64x32 RGB LED Matrix Panel (4mm pitch)

---

### Option 5: Character LCD (Budget Option)

**What You Need:**
- Raspberry Pi Zero W - $10
- 20x4 I2C LCD Display - $10
- Jumper wires - $3
- Power supply - $6
- **Total: ~$30**

**Pros:**
- Very cheap
- Low power
- Simple and reliable
- Easy to read

**Cons:**
- Limited information display
- No graphics
- Requires wiring

**Setup Time:** 1-2 hours

---

## Detailed Setup: Option 2 (Recommended)

### Shopping List

1. **Raspberry Pi 4 (2GB)**
   - Amazon: ~$45
   - Link: Search "Raspberry Pi 4 2GB"

2. **7" Touchscreen Display**
   - Official Raspberry Pi Touch Display: $60
   - Amazon: Search "Raspberry Pi 7 inch touchscreen"

3. **SanDisk 32GB microSD Card**
   - Amazon: ~$8
   - Link: Search "SanDisk 32GB microSD"

4. **Official Raspberry Pi Power Supply**
   - Amazon: ~$8
   - 15W USB-C (5.1V 3A)

5. **SmartiPi Touch 2 Case**
   - Amazon: ~$30
   - Link: Search "SmartiPi Touch 2"

**Total: ~$150**

### Assembly Instructions

1. **Attach Display to Raspberry Pi:**
   - Connect ribbon cable from display to DSI port on Pi
   - Attach using provided standoffs
   - Connect power jumpers from display to GPIO pins

2. **Install in Case:**
   - Follow SmartiPi case instructions
   - Mount Pi and display in case
   - Organize cables

3. **Insert microSD Card:**
   - Flash Raspberry Pi OS using Raspberry Pi Imager
   - Insert into Pi

4. **Power On:**
   - Connect power supply
   - Boot should show on screen

### Software Setup

1. **Initial Configuration:**
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Git
sudo apt install git -y
```

2. **Install Project:**
```bash
cd ~
git clone <your-repo-url> mta_time
cd mta_time
npm install
```

3. **Configure Environment:**
```bash
cp .env.example .env
nano .env  # Add API key if needed
```

4. **Test Run:**
```bash
npm run web
# Open browser to http://localhost:3000
```

5. **Set Up Auto-Start:**
```bash
# Install PM2
sudo npm install -g pm2

# Start web server
pm2 start web-server.js --name mta-display

# Save PM2 configuration
pm2 save

# Enable PM2 on boot
pm2 startup
# Run the command it outputs
```

6. **Configure Browser Auto-Start:**
```bash
# Install Chromium (if not installed)
sudo apt install chromium-browser -y

# Create autostart directory
mkdir -p ~/.config/autostart

# Create desktop entry
cat > ~/.config/autostart/mta-display.desktop << EOF
[Desktop Entry]
Type=Application
Name=MTA Display
Exec=chromium-browser --kiosk --disable-restore-session-state http://localhost:3000
EOF
```

7. **Reboot:**
```bash
sudo reboot
```

After reboot, the display should automatically show the train times in full-screen mode.

---

## Mounting Options

### Wall Mount
- Use VESA mount adapter for display
- 3M Command strips for lighter setups
- Wall anchor screws for permanent installation

### Desktop Stand
- Picture frame stand
- Tablet stand
- Custom 3D printed stand

### Picture Frame
- Remove glass and backing from 8x10" frame
- Mount 7" display inside
- Adds decorative touch

---

## Power Options

### Always On
- Use standard power supply
- Plug into wall outlet
- Can use smart plug for scheduling

### Battery Powered (for e-ink displays)
- LiPo battery with appropriate regulator
- Solar panel option for continuous operation
- Battery life: 1-7 days depending on refresh rate

---

## Troubleshooting

### Display not working
- Check ribbon cable connection
- Verify DSI port connection
- Check power connections

### Touch not working
- Install touch drivers: `sudo apt install libts-bin`
- Calibrate: `sudo TSLIB_FBDEVICE=/dev/fb0 TSLIB_TSDEVICE=/dev/input/event0 ts_calibrate`

### Web page not loading
- Check if server is running: `pm2 status`
- Check network: `ping localhost`
- Check logs: `pm2 logs mta-display`

---

## Future Hardware Ideas

- **Motion Sensor**: Wake display only when someone approaches
- **RGB LED Strip**: Change color based on train arrival time
- **Speaker**: Audio announcements
- **Button**: Switch between stations or lines
- **Weather Display**: Show weather alongside train times
