const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

// Location configuration
const HOME_LOCATION = {
  name: '107 Skillman Avenue, Brooklyn NY',
  latitude: 40.7088,
  longitude: -73.9504
};

// Station configuration for 107 Skillman Avenue, Brooklyn
const STATIONS = {
  GRAHAM_L: {
    name: 'Graham Av',
    stopId: 'L11',
    line: 'L',
    feedUrl: feedMapper.getEndpointForLine('L'),
    latitude: 40.7140,
    longitude: -73.9440
  },
  LORIMER_L: {
    name: 'Lorimer St',
    stopId: 'L10',
    line: 'L',
    feedUrl: feedMapper.getEndpointForLine('L'),
    latitude: 40.7037,
    longitude: -73.9501
  },
  NASSAU_G: {
    name: 'Nassau Av',
    stopId: 'G28',
    line: 'G',
    feedUrl: feedMapper.getEndpointForLine('G'),
    latitude: 40.7243,
    longitude: -73.9514
  }
};

// Calculate distance between two coordinates in miles using Haversine formula
function calculateDistance(lat1, lon1, lat2, lon2) {
  const R = 3959; // Earth's radius in miles
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a =
    Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

// Select station based on current location
function selectStation(currentLat, currentLon) {
  // Calculate distance from current location to home
  const distanceFromHome = calculateDistance(
    currentLat,
    currentLon,
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude
  );

  // If within 0.1 mile radius of home (107 Skillman Ave), use Lorimer St
  if (distanceFromHome <= 0.1) {
    return STATIONS.LORIMER_L;
  }

  // Otherwise, find the closest station
  let closestStation = STATIONS.GRAHAM_L;
  let minDistance = Infinity;

  for (const [key, station] of Object.entries(STATIONS)) {
    const distance = calculateDistance(
      currentLat,
      currentLon,
      station.latitude,
      station.longitude
    );
    if (distance < minDistance) {
      minDistance = distance;
      closestStation = station;
    }
  }

  return closestStation;
}

// Use Lorimer St when at home (107 Skillman Ave)
const STATION = selectStation(HOME_LOCATION.latitude, HOME_LOCATION.longitude);

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
  console.log(`  Location: ${HOME_LOCATION.name}`);

  // Calculate and display distance from home
  const distanceFromHome = calculateDistance(
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude,
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude
  );

  if (distanceFromHome <= 0.1) {
    console.log('  Using Lorimer St (within 0.1 mile of home)');
  }

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
  console.log(`Location: ${HOME_LOCATION.name}`);

  // Calculate distance from home to selected station
  const distanceToStation = calculateDistance(
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude,
    STATION.latitude,
    STATION.longitude
  );

  console.log(`Selected Station: ${STATION.name} (${STATION.line} train)`);
  console.log(`Distance: ${(distanceToStation * 5280).toFixed(0)} feet (${distanceToStation.toFixed(2)} miles)`);

  const distanceFromHome = calculateDistance(
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude,
    HOME_LOCATION.latitude,
    HOME_LOCATION.longitude
  );

  if (distanceFromHome <= 0.1) {
    console.log('Note: Using Lorimer St because you are within 0.1 mile of home');
  }

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
