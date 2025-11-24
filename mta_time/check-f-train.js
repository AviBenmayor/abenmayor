const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

// 47-50 Sts - Rockefeller Center (F train)
const STATION = {
  name: '47-50 Sts - Rockefeller Ctr',
  stopId: 'D15',  // D15S for Brooklyn-bound (southbound)
  line: 'F'
};

async function getNextFTrain() {
  try {
    const endpoint = feedMapper.getEndpointForLine('F');

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
          // D15S = southbound (to Brooklyn)
          if (stopTime.stopId && stopTime.stopId.startsWith(STATION.stopId + 'S')) {
            const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;

            if (arrivalTime) {
              const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);

              if (arrivalTimestamp > now) {
                const minutesUntilArrival = Math.floor((arrivalTimestamp - now) / 60);

                arrivals.push({
                  line: STATION.line,
                  station: STATION.name,
                  direction: 'Brooklyn',
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
  console.log(`F Train Status - ${STATION.name}`);
  console.log('Direction: To Brooklyn');
  console.log('='.repeat(70));
  console.log();

  const arrivals = await getNextFTrain();

  if (arrivals.length === 0) {
    console.log('No upcoming F trains to Brooklyn found.');
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
