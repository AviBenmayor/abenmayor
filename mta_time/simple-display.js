const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

/**
 * Simple single-line display for LCD screens (16x2 or 20x4)
 * Output format: "L train: 3 min"
 */

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
    let nextArrival = null;

    feed.entity.forEach(entity => {
      if (entity.tripUpdate && entity.tripUpdate.stopTimeUpdate) {
        entity.tripUpdate.stopTimeUpdate.forEach(stopTime => {
          if (stopTime.stopId && stopTime.stopId.startsWith(STATION.stopId)) {
            const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;
            if (arrivalTime) {
              const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);
              if (arrivalTimestamp > now) {
                const minutesAway = Math.floor((arrivalTimestamp - now) / 60);
                if (!nextArrival || minutesAway < nextArrival.minutes) {
                  nextArrival = {
                    minutes: minutesAway,
                    direction: stopTime.stopId.endsWith('N') ? 'Manhattan' : 'Outbound'
                  };
                }
              }
            }
          }
        });
      }
    });

    return nextArrival;
  } catch (error) {
    console.error('Error:', error.message);
    return null;
  }
}

async function displaySimple() {
  const train = await getNextTrain();

  if (train) {
    // Format for 16x2 LCD display
    const line1 = `${STATION.line} train ${train.direction}`;
    const line2 = `Arriving: ${train.minutes} min`;

    console.log(line1);
    console.log(line2);

    // For integration with LCD libraries, return the data
    return {
      line1,
      line2,
      minutes: train.minutes
    };
  } else {
    console.log('No trains found');
    return { line1: 'No trains', line2: 'available', minutes: null };
  }
}

// Run once if called directly
if (require.main === module) {
  displaySimple();
}

// Export for use in other modules (e.g., LCD display driver)
module.exports = { getNextTrain, displaySimple };
