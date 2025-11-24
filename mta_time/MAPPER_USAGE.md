# MTA Feed Mapper - Usage Guide

## Overview

The MTA Feed Mapper provides a clean, centralized way to map NYC subway lines to their GTFS realtime API endpoints. No more hardcoding URLs or managing feed groups manually.

## Quick Start

```javascript
const feedMapper = require('./lib/mta-feed-mapper');

// Get endpoint for a specific line
const endpoint = feedMapper.getEndpointForLine('L');
// Returns: https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l

// Get endpoint with API key
const config = feedMapper.getEndpointConfig('6', 'your-api-key');
// Returns: { url: '...', headers: { 'x-api-key': 'your-api-key' } }
```

## Configuration File

All train line mappings are stored in `config/mta-feeds.yaml`:

- **27 train lines** mapped to their feeds
- **8 feed groups** with complete metadata
- Official MTA colors for each line
- Division information (A/B Division)
- Feed descriptions and endpoints

## Available Functions

### Core Functions

#### `getEndpointForLine(line)`
Get the full API endpoint URL for a train line.

```javascript
feedMapper.getEndpointForLine('A');
// => 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-ace'

feedMapper.getEndpointForLine('6');
// => 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs'
```

**Parameters:**
- `line` (string) - Train line identifier (e.g., 'L', 'A', '6', 'SIR')

**Returns:** Full endpoint URL

**Throws:** Error if line is invalid

---

#### `getFeedGroupForLine(line)`
Get the feed group name for a train line.

```javascript
feedMapper.getFeedGroupForLine('L');  // => 'l'
feedMapper.getFeedGroupForLine('A');  // => 'ace'
feedMapper.getFeedGroupForLine('6');  // => 'numbered'
```

**Parameters:**
- `line` (string) - Train line identifier

**Returns:** Feed group name (string) or null if invalid

---

#### `isValidLine(line)`
Check if a train line exists in the system.

```javascript
feedMapper.isValidLine('L');   // => true
feedMapper.isValidLine('X');   // => false
feedMapper.isValidLine('99');  // => false
```

**Parameters:**
- `line` (string) - Train line to validate

**Returns:** Boolean

---

### Information Functions

#### `getAllLines()`
Get all valid train line identifiers.

```javascript
const lines = feedMapper.getAllLines();
// => ['1', '2', '3', '4', '5', '6', '7', 'A', 'B', 'C', ...]
```

**Returns:** Array of strings (27 total lines)

---

#### `getLinesInFeed(feedGroup)`
Get all train lines that belong to a specific feed.

```javascript
feedMapper.getLinesInFeed('ace');
// => ['A', 'C', 'E', 'H', 'FS']

feedMapper.getLinesInFeed('numbered');
// => ['1', '2', '3', '4', '5', '6', '7', 'S', 'GS']
```

**Parameters:**
- `feedGroup` (string) - Feed group name

**Returns:** Array of line identifiers

**Throws:** Error if feed group doesn't exist

---

#### `getAllFeedGroups()`
Get all feed group names.

```javascript
const feeds = feedMapper.getAllFeedGroups();
// => ['ace', 'bdfm', 'g', 'jz', 'nqrw', 'l', 'numbered', 'si']
```

**Returns:** Array of feed group names (8 total)

---

#### `getFeedInfo(feedGroup)`
Get complete information about a feed group.

```javascript
const info = feedMapper.getFeedInfo('l');
// Returns:
// {
//   name: 'L',
//   endpoint: 'nyct%2Fgtfs-l',
//   full_url: 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l',
//   division: 'B Division (BMT)',
//   lines: ['L'],
//   description: '14th Street-Canarsie Local (L)'
// }
```

**Parameters:**
- `feedGroup` (string) - Feed group name

**Returns:** Object with feed details

---

### Utility Functions

#### `getLineColor(line)`
Get the official MTA hex color for a train line.

```javascript
feedMapper.getLineColor('L');  // => '#A7A9AC' (Gray)
feedMapper.getLineColor('A');  // => '#0039A6' (Blue)
feedMapper.getLineColor('1');  // => '#EE352E' (Red)
```

**Parameters:**
- `line` (string) - Train line identifier

**Returns:** Hex color code (string) or null

---

#### `getEndpointConfig(line, apiKey)`
Get endpoint URL and headers for API requests.

```javascript
const config = feedMapper.getEndpointConfig('L', 'my-api-key');
// Returns:
// {
//   url: 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/nyct%2Fgtfs-l',
//   headers: { 'x-api-key': 'my-api-key' }
// }

// Without API key
const config2 = feedMapper.getEndpointConfig('A');
// Returns: { url: '...', headers: {} }
```

**Parameters:**
- `line` (string) - Train line identifier
- `apiKey` (string, optional) - MTA API key

**Returns:** Object with `url` and `headers`

---

#### `getLinesByFeed()`
Group all lines by their feed.

```javascript
const grouped = feedMapper.getLinesByFeed();
// Returns:
// {
//   ace: ['A', 'C', 'E', 'H', 'FS'],
//   bdfm: ['B', 'D', 'F', 'M'],
//   g: ['G'],
//   ...
// }
```

**Returns:** Object mapping feed groups to line arrays

---

#### `getLinesByColor(color)`
Find all lines with a specific color.

```javascript
const redLines = feedMapper.getLinesByColor('#EE352E');
// => ['1', '2', '3']

const blueLines = feedMapper.getLinesByColor('#0039A6');
// => ['A', 'C', 'E', 'SIR']
```

**Parameters:**
- `color` (string) - Hex color code

**Returns:** Array of line identifiers

---

#### `getMetadata()`
Get API metadata information.

```javascript
const metadata = feedMapper.getMetadata();
// Returns:
// {
//   base_url: 'https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds',
//   api_version: '2.0.0',
//   update_frequency_seconds: 30,
//   data_format: 'GTFS-Realtime Protocol Buffers',
//   api_key_required: false,
//   api_key_header: 'x-api-key'
// }
```

**Returns:** Object with metadata

---

## Complete Line Reference

### Numbered Lines (A Division - IRT)
| Line | Feed | Color | Name |
|------|------|-------|------|
| 1, 2, 3 | numbered | Red (#EE352E) | Broadway-7th Ave |
| 4, 5, 6 | numbered | Green (#00933C) | Lexington Ave |
| 7 | numbered | Purple (#B933AD) | Flushing |
| S | numbered | Gray (#808183) | 42nd St Shuttle |

### Lettered Lines (B Division - IND/BMT)
| Line | Feed | Color | Name |
|------|------|-------|------|
| A, C, E | ace | Blue (#0039A6) | 8th Avenue |
| B, D, F, M | bdfm | Orange (#FF6319) | 6th Avenue |
| G | g | Light Green (#6CBE45) | Crosstown |
| J, Z | jz | Brown (#996633) | Nassau St |
| L | l | Gray (#A7A9AC) | Canarsie |
| N, Q, R, W | nqrw | Yellow (#FCCC0A) | Broadway |

### Special Services
| Line | Feed | Description |
|------|------|-------------|
| H | ace | Rockaway Park Shuttle |
| FS | ace | Franklin Avenue Shuttle |
| GS | numbered | Grand Central Shuttle |
| SIR | si | Staten Island Railway |

## Usage Examples

### Example 1: Fetch Real-Time Data for Any Line

```javascript
const feedMapper = require('./lib/mta-feed-mapper');
const fetch = require('node-fetch');
const GtfsRealtimeBindings = require('gtfs-realtime-bindings');

async function getTrainData(line) {
  // Validate the line
  if (!feedMapper.isValidLine(line)) {
    throw new Error(`Invalid train line: ${line}`);
  }

  // Get endpoint configuration
  const config = feedMapper.getEndpointConfig(line, process.env.MTA_API_KEY);

  // Fetch the data
  const response = await fetch(config.url, { headers: config.headers });
  const buffer = await response.arrayBuffer();
  const feed = GtfsRealtimeBindings.transit_realtime.FeedMessage.decode(
    new Uint8Array(buffer)
  );

  return feed;
}

// Usage
const lTrainData = await getTrainData('L');
const aTrainData = await getTrainData('A');
```

### Example 2: Monitor Multiple Lines

```javascript
const linesToMonitor = ['L', 'G', 'A', '6'];

async function monitorLines(lines) {
  for (const line of lines) {
    const endpoint = feedMapper.getEndpointForLine(line);
    const color = feedMapper.getLineColor(line);

    console.log(`${line} train (${color}): ${endpoint}`);

    // Fetch and process data for each line...
  }
}

monitorLines(linesToMonitor);
```

### Example 3: Build a Line Selector UI

```javascript
// Get all lines grouped by color
function getLinesByColorGroup() {
  const allLines = feedMapper.getAllLines();
  const grouped = {};

  allLines.forEach(line => {
    const color = feedMapper.getLineColor(line);
    if (!grouped[color]) {
      grouped[color] = [];
    }
    grouped[color].push(line);
  });

  return grouped;
}

const colorGroups = getLinesByColorGroup();
// Use this to build a UI with color-coded train line buttons
```

### Example 4: Get All Feeds for Monitoring

```javascript
// Monitor all 8 feed endpoints
async function monitorAllFeeds() {
  const feeds = feedMapper.getAllFeedGroups();

  for (const feedGroup of feeds) {
    const info = feedMapper.getFeedInfo(feedGroup);
    console.log(`Feed: ${info.name}`);
    console.log(`  Lines: ${info.lines.join(', ')}`);
    console.log(`  URL: ${info.full_url}`);
    console.log(`  Division: ${info.division}`);
    console.log();

    // Fetch data from this feed...
  }
}
```

## Testing

Run the test suite to verify all functions:

```bash
node test-mapper.js
```

This will test:
- Line-to-endpoint mapping
- Feed group lookups
- Line validation
- Color lookups
- All utility functions

## Configuration

The YAML configuration file (`config/mta-feeds.yaml`) contains:

1. **Metadata** - API version, base URL, update frequency
2. **Feeds** - Complete feed group definitions
3. **Line-to-Feed Mapping** - Direct line lookups
4. **Line Colors** - Official MTA colors
5. **Notes** - Important usage information

To modify the configuration:
1. Edit `config/mta-feeds.yaml`
2. Restart your application
3. The mapper will automatically reload the new config

## Error Handling

The mapper throws descriptive errors for invalid inputs:

```javascript
try {
  const endpoint = feedMapper.getEndpointForLine('X');
} catch (error) {
  console.error(error.message);
  // => "Invalid train line: X"
}

try {
  const lines = feedMapper.getLinesInFeed('invalid');
} catch (error) {
  console.error(error.message);
  // => "Invalid feed group: invalid"
}
```

## Benefits

1. **Centralized Configuration** - All mappings in one YAML file
2. **Type Safety** - Validation for all line inputs
3. **Easy Updates** - Change endpoints without modifying code
4. **Rich Metadata** - Colors, divisions, descriptions included
5. **Flexible Usage** - Multiple ways to query the data
6. **Well Tested** - Comprehensive test suite included
7. **No Hardcoding** - Dynamic endpoint resolution

## Feed Update Frequency

According to MTA documentation:
- Feeds update approximately every **30 seconds**
- Data format: **GTFS-Realtime Protocol Buffers**
- API keys are **optional** (as of v2.0.0)

## Support

For issues or questions about:
- **MTA API**: Visit https://api.mta.info/
- **GTFS Format**: See https://www.mta.info/developers
- **This Mapper**: Check `test-mapper.js` for examples
