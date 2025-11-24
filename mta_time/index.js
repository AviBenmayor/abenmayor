const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

// Station configuration for 107 Skillman Avenue, Brooklyn
const STATIONS = {
  GRAHAM_L: {
    name: 'Graham Av',
    stopId: 'L11',
    line: 'L',
    feedUrl: feedMapper.getEndpointForLine('L')
  },
  NASSAU_G: {
    name: 'Nassau Av',
    stopId: 'G28',
    line: 'G',
    feedUrl: feedMapper.getEndpointForLine('G')
  }
};

// Use Graham Av (L train) as the primary station - closest to 107 Skillman Ave
const STATION = STATIONS.GRAHAM_L;

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

    const now = Date.now() / 1000; // Current time in seconds
    const arrivals = [];

    // Parse the feed for our station
    feed.entity.forEach(entity => {
      if (entity.tripUpdate && entity.tripUpdate.stopTimeUpdate) {
        entity.tripUpdate.stopTimeUpdate.forEach(stopTime => {
          // Check if this stop matches our station
          // Stop IDs can be in format "L11N" or "L11S" (N=northbound, S=southbound)
          if (stopTime.stopId && stopTime.stopId.startsWith(STATION.stopId)) {
            const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;

            if (arrivalTime) {
              const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);

              // Only include future arrivals
              if (arrivalTimestamp > now) {
                const minutesUntilArrival = Math.floor((arrivalTimestamp - now) / 60);
                const direction = stopTime.stopId.endsWith('N') ? 'Manhattan' :
                                stopTime.stopId.endsWith('S') ? 'Outbound' : 'Unknown';

                arrivals.push({
                  line: STATION.line,
                  station: STATION.name,
                  direction: direction,
                  minutesAway: minutesUntilArrival,
                  arrivalTime: new Date(arrivalTimestamp * 1000)
                });
              }
            }
          }
        });
      }
    });

    // Sort by arrival time
    arrivals.sort((a, b) => a.minutesAway - b.minutesAway);

    return arrivals;
  } catch (error) {
    console.error('Error fetching train data:', error.message);
    throw error;
  }
}

function displayTrainInfo(arrivals) {
  console.clear();
  console.log('='.repeat(50));
  console.log(`  MTA TRAIN TRACKER - ${STATION.name} Station (${STATION.line} train)`);
  console.log('  Location: 107 Skillman Avenue, Brooklyn NY');
  console.log('='.repeat(50));
  console.log();

  if (arrivals.length === 0) {
    console.log('  No upcoming trains found.');
  } else {
    const nextTrain = arrivals[0];

    // Display the next train prominently
    console.log('  NEXT TRAIN:');
    console.log(`  ${nextTrain.line} train to ${nextTrain.direction}`);
    console.log(`  Arriving in: ${nextTrain.minutesAway} minute${nextTrain.minutesAway !== 1 ? 's' : ''}`);
    console.log(`  Time: ${nextTrain.arrivalTime.toLocaleTimeString()}`);

    // Show upcoming trains
    if (arrivals.length > 1) {
      console.log();
      console.log('  UPCOMING TRAINS:');
      arrivals.slice(1, 5).forEach((train, index) => {
        console.log(`  ${index + 2}. ${train.line} to ${train.direction} - ${train.minutesAway} min (${train.arrivalTime.toLocaleTimeString()})`);
      });
    }
  }

  console.log();
  console.log('='.repeat(50));
  console.log(`  Last updated: ${new Date().toLocaleTimeString()}`);
  console.log('='.repeat(50));
}

async function main() {
  console.log('Starting MTA Train Tracker...');
  console.log(`Monitoring: ${STATION.name} Station (${STATION.line} train)`);
  console.log();

  // Initial fetch
  try {
    const arrivals = await getNextTrain();
    displayTrainInfo(arrivals);
  } catch (error) {
    console.error('Failed to fetch initial train data:', error.message);
  }

  // Update every 30 seconds
  setInterval(async () => {
    try {
      const arrivals = await getNextTrain();
      displayTrainInfo(arrivals);
    } catch (error) {
      console.error('Update failed:', error.message);
    }
  }, 30000); // 30 seconds
}

// Run the application
main();
