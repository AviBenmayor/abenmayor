const http = require('http');
const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

const PORT = process.env.PORT || 3000;

const STATION = {
  name: 'Graham Av',
  stopId: 'L11',
  line: 'L',
  feedUrl: feedMapper.getEndpointForLine('L')
};

async function getNextTrain() {
  try {
    const headers = {};
    if (process.env.MTA_API_KEY) {
      headers['x-api-key'] = process.env.MTA_API_KEY;
    }

    const response = await fetch(STATION.feedUrl, { headers });
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const buffer = await response.arrayBuffer();
    const feed = GtfsRealtimeBindings.transit_realtime.FeedMessage.decode(
      new Uint8Array(buffer)
    );

    const now = Date.now() / 1000;
    const arrivals = [];

    feed.entity.forEach(entity => {
      if (entity.tripUpdate && entity.tripUpdate.stopTimeUpdate) {
        entity.tripUpdate.stopTimeUpdate.forEach(stopTime => {
          if (stopTime.stopId && stopTime.stopId.startsWith(STATION.stopId)) {
            const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;
            if (arrivalTime) {
              const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);
              if (arrivalTimestamp > now) {
                const minutesAway = Math.floor((arrivalTimestamp - now) / 60);
                const direction = stopTime.stopId.endsWith('N') ? 'Manhattan' : 'Outbound';

                arrivals.push({
                  line: STATION.line,
                  station: STATION.name,
                  direction: direction,
                  minutesAway: minutesAway,
                  arrivalTime: new Date(arrivalTimestamp * 1000)
                });
              }
            }
          }
        });
      }
    });

    arrivals.sort((a, b) => a.minutesAway - b.minutesAway);
    return arrivals;
  } catch (error) {
    console.error('Error fetching train data:', error.message);
    return [];
  }
}

function generateHTML(arrivals) {
  const nextTrain = arrivals[0];
  const hasTrains = arrivals.length > 0;

  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MTA Train Time - ${STATION.name}</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: 'Helvetica Neue', Arial, sans-serif;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }

    .container {
      background: rgba(255, 255, 255, 0.1);
      backdrop-filter: blur(10px);
      border-radius: 20px;
      padding: 40px;
      max-width: 600px;
      width: 100%;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }

    .station-info {
      text-align: center;
      margin-bottom: 30px;
      padding-bottom: 20px;
      border-bottom: 2px solid rgba(255, 255, 255, 0.3);
    }

    .station-name {
      font-size: 1.2em;
      opacity: 0.9;
      margin-bottom: 5px;
    }

    .station-address {
      font-size: 0.9em;
      opacity: 0.7;
    }

    .next-train {
      text-align: center;
      margin-bottom: 30px;
    }

    .train-line {
      display: inline-block;
      background: white;
      color: #0039a6;
      font-weight: bold;
      font-size: 2em;
      padding: 10px 20px;
      border-radius: 50%;
      margin-bottom: 15px;
      min-width: 70px;
      height: 70px;
      line-height: 50px;
    }

    .minutes-display {
      font-size: 5em;
      font-weight: bold;
      margin: 20px 0;
      text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
    }

    .minutes-label {
      font-size: 1.5em;
      opacity: 0.9;
    }

    .direction {
      font-size: 1.2em;
      opacity: 0.8;
      margin-top: 10px;
    }

    .upcoming-trains {
      margin-top: 30px;
    }

    .upcoming-title {
      font-size: 1.1em;
      margin-bottom: 15px;
      opacity: 0.9;
    }

    .upcoming-train {
      background: rgba(255, 255, 255, 0.1);
      padding: 12px 15px;
      border-radius: 8px;
      margin-bottom: 8px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .no-trains {
      text-align: center;
      font-size: 1.5em;
      opacity: 0.8;
      padding: 40px 0;
    }

    .last-update {
      text-align: center;
      margin-top: 30px;
      opacity: 0.6;
      font-size: 0.9em;
    }

    @media (max-width: 600px) {
      .minutes-display {
        font-size: 3.5em;
      }
      .container {
        padding: 20px;
      }
    }
  </style>
  <script>
    // Auto-refresh every 30 seconds
    setTimeout(() => location.reload(), 30000);
  </script>
</head>
<body>
  <div class="container">
    <div class="station-info">
      <div class="station-name">${STATION.name} Station</div>
      <div class="station-address">107 Skillman Avenue, Brooklyn NY</div>
    </div>

    ${hasTrains ? `
    <div class="next-train">
      <div class="train-line">${nextTrain.line}</div>
      <div class="direction">to ${nextTrain.direction}</div>
      <div class="minutes-display">${nextTrain.minutesAway}</div>
      <div class="minutes-label">minute${nextTrain.minutesAway !== 1 ? 's' : ''}</div>
    </div>

    ${arrivals.length > 1 ? `
    <div class="upcoming-trains">
      <div class="upcoming-title">Upcoming Trains</div>
      ${arrivals.slice(1, 5).map(train => `
        <div class="upcoming-train">
          <span>${train.line} to ${train.direction}</span>
          <span><strong>${train.minutesAway} min</strong></span>
        </div>
      `).join('')}
    </div>
    ` : ''}
    ` : `
    <div class="no-trains">No upcoming trains</div>
    `}

    <div class="last-update">
      Last updated: ${new Date().toLocaleTimeString()}
    </div>
  </div>
</body>
</html>
  `;
}

const server = http.createServer(async (req, res) => {
  if (req.url === '/') {
    const arrivals = await getNextTrain();
    const html = generateHTML(arrivals);

    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html);
  } else if (req.url === '/api') {
    const arrivals = await getNextTrain();

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      station: STATION.name,
      line: STATION.line,
      arrivals: arrivals,
      timestamp: new Date().toISOString()
    }));
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
  }
});

server.listen(PORT, () => {
  console.log(`MTA Train Time web server running at http://localhost:${PORT}`);
  console.log(`Monitoring: ${STATION.name} Station (${STATION.line} train)`);
  console.log(`\nOpen http://localhost:${PORT} in your browser`);
  console.log(`API available at http://localhost:${PORT}/api`);
});
