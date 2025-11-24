const feedMapper = require('./lib/mta-feed-mapper');

console.log('='.repeat(70));
console.log('MTA Feed Mapper - Test Suite');
console.log('='.repeat(70));
console.log();

// Test 1: Get endpoint for specific lines
console.log('1. Testing getEndpointForLine():');
console.log('-'.repeat(70));
const testLines = ['L', 'A', '6', 'G', 'N', 'SIR'];
testLines.forEach(line => {
  try {
    const endpoint = feedMapper.getEndpointForLine(line);
    console.log(`   ${line.padEnd(4)} => ${endpoint}`);
  } catch (error) {
    console.log(`   ${line.padEnd(4)} => ERROR: ${error.message}`);
  }
});
console.log();

// Test 2: Get feed group for lines
console.log('2. Testing getFeedGroupForLine():');
console.log('-'.repeat(70));
testLines.forEach(line => {
  const feedGroup = feedMapper.getFeedGroupForLine(line);
  console.log(`   ${line.padEnd(4)} => ${feedGroup || 'null'}`);
});
console.log();

// Test 3: Get all lines
console.log('3. Testing getAllLines():');
console.log('-'.repeat(70));
const allLines = feedMapper.getAllLines();
console.log(`   Total lines: ${allLines.length}`);
console.log(`   Lines: ${allLines.join(', ')}`);
console.log();

// Test 4: Get lines in each feed
console.log('4. Testing getLinesInFeed():');
console.log('-'.repeat(70));
const feedGroups = feedMapper.getAllFeedGroups();
feedGroups.forEach(feed => {
  const lines = feedMapper.getLinesInFeed(feed);
  console.log(`   ${feed.padEnd(10)} => [${lines.join(', ')}]`);
});
console.log();

// Test 5: Validate lines
console.log('5. Testing isValidLine():');
console.log('-'.repeat(70));
const validationTests = ['L', 'A', '6', 'X', 'Z', '99'];
validationTests.forEach(line => {
  const isValid = feedMapper.isValidLine(line);
  console.log(`   ${line.padEnd(4)} => ${isValid ? 'VALID' : 'INVALID'}`);
});
console.log();

// Test 6: Get line colors
console.log('6. Testing getLineColor():');
console.log('-'.repeat(70));
const colorTests = ['L', 'A', '1', 'G', 'N'];
colorTests.forEach(line => {
  const color = feedMapper.getLineColor(line);
  console.log(`   ${line.padEnd(4)} => ${color || 'null'}`);
});
console.log();

// Test 7: Get feed info
console.log('7. Testing getFeedInfo():');
console.log('-'.repeat(70));
const feedInfo = feedMapper.getFeedInfo('l');
console.log(`   Feed: ${feedInfo.name}`);
console.log(`   Endpoint: ${feedInfo.endpoint}`);
console.log(`   Division: ${feedInfo.division}`);
console.log(`   Lines: [${feedInfo.lines.join(', ')}]`);
console.log(`   Description: ${feedInfo.description}`);
console.log();

// Test 8: Get endpoint config with API key
console.log('8. Testing getEndpointConfig():');
console.log('-'.repeat(70));
const config = feedMapper.getEndpointConfig('L', 'test-api-key-123');
console.log(`   URL: ${config.url}`);
console.log(`   Headers: ${JSON.stringify(config.headers)}`);
console.log();

// Test 9: Get metadata
console.log('9. Testing getMetadata():');
console.log('-'.repeat(70));
const metadata = feedMapper.getMetadata();
console.log(`   Base URL: ${metadata.base_url}`);
console.log(`   API Version: ${metadata.api_version}`);
console.log(`   Update Frequency: ${metadata.update_frequency_seconds}s`);
console.log(`   API Key Required: ${metadata.api_key_required}`);
console.log();

// Test 10: Get lines by feed
console.log('10. Testing getLinesByFeed():');
console.log('-'.repeat(70));
const linesByFeed = feedMapper.getLinesByFeed();
Object.entries(linesByFeed).forEach(([feed, lines]) => {
  console.log(`   ${feed.padEnd(10)} => [${lines.join(', ')}]`);
});
console.log();

// Test 11: Get lines by color
console.log('11. Testing getLinesByColor():');
console.log('-'.repeat(70));
const redLines = feedMapper.getLinesByColor('#EE352E');
const blueLines = feedMapper.getLinesByColor('#0039A6');
console.log(`   Red (#EE352E): [${redLines.join(', ')}]`);
console.log(`   Blue (#0039A6): [${blueLines.join(', ')}]`);
console.log();

console.log('='.repeat(70));
console.log('All tests completed!');
console.log('='.repeat(70));
