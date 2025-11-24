# MTA Train Time Display

A real-time train arrival display for the Graham Avenue (L train) station, the closest station to 107 Skillman Avenue, Brooklyn NY.

## Overview

This project displays the next train arrival time using the MTA's real-time GTFS data feed. It's designed to run on a Raspberry Pi or similar device with a display.

## Station Information

- **Primary Station**: Graham Av (L train)
- **Stop ID**: L11
- **Location**: Closest to 107 Skillman Avenue, Brooklyn
- **Alternative**: Nassau Av (G train) - Stop ID: G28

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Get MTA API Key (Optional)

While API keys may not be required for version 2.0.0+, you can get one from:
- Visit: https://api.mta.info/#/signup
- Sign up for a free API key
- Copy your API key

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your API key (if needed)
```

### 4. Run the Application

```bash
npm start
```

The display will update every 30 seconds with the next train arrival time.

## MTA Feed Mapper

This project includes a powerful mapping system for all NYC subway lines. Instead of hardcoding API endpoints, you can use the feed mapper to dynamically resolve endpoints for any train line.

### Features

- **27 train lines mapped** (1-7, A-Z, SIR, shuttles)
- **8 feed groups** with complete metadata
- **Official MTA colors** for each line
- **Helper functions** for easy integration
- **YAML configuration** for easy updates

### Quick Example

```javascript
const feedMapper = require('./lib/mta-feed-mapper');

// Get endpoint for any line
const endpoint = feedMapper.getEndpointForLine('A');
// => 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace'

// Validate a line
feedMapper.isValidLine('L');  // => true

// Get all lines
const allLines = feedMapper.getAllLines();
// => ['1', '2', '3', 'A', 'B', 'C', 'L', 'G', ...]

// Get line color
const color = feedMapper.getLineColor('L');
// => '#A7A9AC'
```

### Available Functions

- `getEndpointForLine(line)` - Get API endpoint for a train line
- `getFeedGroupForLine(line)` - Get feed group name
- `isValidLine(line)` - Validate a train line
- `getAllLines()` - Get all valid lines
- `getLinesInFeed(feedGroup)` - Get lines in a feed
- `getLineColor(line)` - Get official MTA color
- `getEndpointConfig(line, apiKey)` - Get URL with headers
- And more...

See **MAPPER_USAGE.md** for complete documentation and examples.

### Test the Mapper

```bash
node test-mapper.js
```

## Hardware Setup Options

### Option 1: Raspberry Pi with HDMI Display

**Hardware Needed:**
- Raspberry Pi (3, 4, or Zero W)
- HDMI monitor or small HDMI display
- Power supply
- MicroSD card (16GB+)

**Setup:**
1. Install Raspberry Pi OS Lite
2. Install Node.js:
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
   sudo apt-get install -y nodejs
   ```
3. Clone this project
4. Run `npm install`
5. Set up auto-start (see below)

### Option 2: Raspberry Pi with E-Ink Display

**Hardware Needed:**
- Raspberry Pi
- Waveshare e-Paper HAT (2.13", 2.9", or larger)
- Power supply

**Note**: E-ink version requires additional code for display rendering (not included yet)

### Option 3: ESP32/ESP8266 with LCD

**Hardware Needed:**
- ESP32 or ESP8266 board
- I2C LCD display (16x2 or 20x4)
- Power supply

**Note**: Requires porting to C++/Arduino (not included)

## Auto-Start on Boot (Raspberry Pi)

### Method 1: Using systemd

Create a service file:

```bash
sudo nano /etc/systemd/system/mta-train.service
```

Add:

```ini
[Unit]
Description=MTA Train Time Display
After=network.target

[Service]
ExecStart=/usr/bin/node /home/pi/mta_time/index.js
WorkingDirectory=/home/pi/mta_time
StandardOutput=inherit
StandardError=inherit
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable mta-train.service
sudo systemctl start mta-train.service
```

### Method 2: Using PM2

```bash
sudo npm install -g pm2
pm2 start index.js --name mta-train
pm2 save
pm2 startup
```

## Switching Stations

To switch between Graham Av (L) and Nassau Av (G) stations, edit `index.js`:

```javascript
// Change this line:
const STATION = STATIONS.GRAHAM_L;

// To:
const STATION = STATIONS.NASSAU_G;
```

Or modify the `STATION` object to use a different station entirely.

## Display Customization

The display shows:
- Next train line and direction
- Minutes until arrival
- Arrival time
- Up to 4 upcoming trains
- Last update timestamp

You can customize the display format by modifying the `displayTrainInfo()` function.

## Hardware Display Ideas

### Simple Setup
- Connect Raspberry Pi to any HDMI monitor
- Set terminal to full screen
- Use large font size in terminal settings

### Advanced Setup
- Use a dedicated small display (7" touchscreen)
- Mount in a picture frame
- Add a case for a clean look

### Professional Setup
- Use LED matrix display
- Create custom PCB
- 3D print enclosure

## Troubleshooting

### No data showing
- Check internet connection
- Verify API key (if using one)
- Check if MTA API is operational: https://api.mta.info/

### Empty arrivals
- Train may not be running (check MTA schedule)
- Late night service may be reduced
- Verify correct stop ID

### Connection errors
- Check firewall settings
- Ensure outbound HTTPS is allowed
- Verify DNS resolution

## API Information

- **Feed Type**: GTFS-Realtime (Protocol Buffers)
- **Update Frequency**: Every 30 seconds
- **Data Source**: MTA Real-Time Data Feeds

## Future Enhancements

- [ ] E-ink display support
- [ ] LED matrix display support
- [ ] Web interface for configuration
- [ ] Multiple station monitoring
- [ ] Service alert notifications
- [ ] Historical arrival data
- [ ] Mobile app companion

## Resources

- [MTA Developer Resources](https://www.mta.info/developers)
- [MTA Real-Time Data Feeds](https://datamine.mta.info/)
- [GTFS-Realtime Reference](https://www.mta.info/document/134521)

## License

MIT
