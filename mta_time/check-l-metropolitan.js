const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

// Lorimer St (L train) - closest L train station to Metropolitan Ave
// Note: Metropolitan Ave itself is served by the G train (G29)
// Lorimer St (L10) is the L train station in the Metropolitan Ave area
const STATION = {
  name: 'Lorimer St',
  stopId: 'L10',  // L10N for Manhattan-bound (northbound)
  line: 'L'
};

async function getNextLTrain() {
  try {
    const endpoint = feedMapper.getEndpointForLine('L');

    const headers = {};
    if (process.env.MTA_API_KEY) {
      headers['x-api-key'] = process.env.MTA_API_KEY;
    }

    const response = await fetch(endpoint, { headers });

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
          // L10N = northbound (to Manhattan)
          if (stopTime.stopId && stopTime.stopId.startsWith(STATION.stopId + 'N')) {
            const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;

            if (arrivalTime) {
              const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);

              if (arrivalTimestamp > now) {
                const minutesUntilArrival = Math.floor((arrivalTimestamp - now) / 60);

                arrivals.push({
                  line: STATION.line,
                  station: STATION.name,
                  direction: 'Manhattan',
                  minutesAway: minutesUntilArrival,
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
    throw error;
  }
}

async function main() {
  console.log('='.repeat(70));
  console.log(`L Train Status - ${STATION.name}`);
  console.log('Direction: To Manhattan');
  console.log('Note: Lorimer St is the L train station near Metropolitan Ave');
  console.log('      (Metropolitan Ave itself is served by the G train)');
  console.log('='.repeat(70));
  console.log();

  const arrivals = await getNextLTrain();

  if (arrivals.length === 0) {
    console.log('No upcoming L trains to Manhattan found.');
  } else {
    const nextTrain = arrivals[0];

    console.log('NEXT TRAIN:');
    console.log(`  ${nextTrain.line} train to ${nextTrain.direction}`);
    console.log(`  Arriving in: ${nextTrain.minutesAway} minute${nextTrain.minutesAway !== 1 ? 's' : ''}`);
    console.log(`  Time: ${nextTrain.arrivalTime.toLocaleTimeString()}`);

    if (arrivals.length > 1) {
      console.log();
      console.log('UPCOMING TRAINS:');
      arrivals.slice(1, 5).forEach((train, index) => {
        console.log(`  ${index + 2}. ${train.line} to ${train.direction} - ${train.minutesAway} min (${train.arrivalTime.toLocaleTimeString()})`);
      });
    }
  }

  console.log();
  console.log('='.repeat(70));
  console.log(`Last updated: ${new Date().toLocaleTimeString()}`);
  console.log('='.repeat(70));
}

main();
