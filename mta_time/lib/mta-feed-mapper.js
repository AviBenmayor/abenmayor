const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

/**
 * MTA Feed Mapper
 * Utility library for mapping NYC subway lines to their GTFS realtime feed endpoints
 */

class MTAFeedMapper {
  constructor() {
    this.config = null;
    this.loadConfig();
  }

  /**
   * Load the YAML configuration file
   */
  loadConfig() {
    try {
      const configPath = path.join(__dirname, '..', 'config', 'mta-feeds.yaml');
      const fileContents = fs.readFileSync(configPath, 'utf8');
      this.config = yaml.load(fileContents);
    } catch (error) {
      throw new Error(`Failed to load MTA feed configuration: ${error.message}`);
    }
  }

  /**
   * Get the API endpoint URL for a specific train line
   * @param {string} line - The train line (e.g., 'L', 'A', '6', 'SIR')
   * @returns {string} The full API endpoint URL
   * @throws {Error} If the line is invalid
   */
  getEndpointForLine(line) {
    const feedGroup = this.getFeedGroupForLine(line);
    if (!feedGroup) {
      throw new Error(`Invalid train line: ${line}`);
    }
    return this.config.feeds[feedGroup].full_url;
  }

  /**
   * Get the feed group name for a specific train line
   * @param {string} line - The train line (e.g., 'L', 'A', '6', 'SIR')
   * @returns {string|null} The feed group name or null if invalid
   */
  getFeedGroupForLine(line) {
    const normalizedLine = String(line).toUpperCase();
    return this.config.line_to_feed[normalizedLine] || null;
  }

  /**
   * Get all valid train lines
   * @returns {Array<string>} Array of all train line identifiers
   */
  getAllLines() {
    return Object.keys(this.config.line_to_feed);
  }

  /**
   * Get all lines that belong to a specific feed group
   * @param {string} feedGroup - The feed group name (e.g., 'ace', 'bdfm', 'l')
   * @returns {Array<string>} Array of line identifiers in this feed
   */
  getLinesInFeed(feedGroup) {
    const feed = this.config.feeds[feedGroup];
    if (!feed) {
      throw new Error(`Invalid feed group: ${feedGroup}`);
    }
    return feed.lines;
  }

  /**
   * Check if a train line is valid
   * @param {string} line - The train line to validate
   * @returns {boolean} True if the line exists
   */
  isValidLine(line) {
    const normalizedLine = String(line).toUpperCase();
    return normalizedLine in this.config.line_to_feed;
  }

  /**
   * Get the official MTA color for a train line
   * @param {string} line - The train line
   * @returns {string|null} Hex color code or null if not found
   */
  getLineColor(line) {
    const normalizedLine = String(line).toUpperCase();
    return this.config.line_colors[normalizedLine] || null;
  }

  /**
   * Get complete information about a feed group
   * @param {string} feedGroup - The feed group name
   * @returns {object} Feed information including name, endpoint, lines, etc.
   */
  getFeedInfo(feedGroup) {
    const feed = this.config.feeds[feedGroup];
    if (!feed) {
      throw new Error(`Invalid feed group: ${feedGroup}`);
    }
    return { ...feed };
  }

  /**
   * Get all feed groups
   * @returns {Array<string>} Array of feed group names
   */
  getAllFeedGroups() {
    return Object.keys(this.config.feeds);
  }

  /**
   * Get the base URL for MTA API
   * @returns {string} Base URL
   */
  getBaseUrl() {
    return this.config.metadata.base_url;
  }

  /**
   * Get metadata about the MTA API
   * @returns {object} Metadata including version, update frequency, etc.
   */
  getMetadata() {
    return { ...this.config.metadata };
  }

  /**
   * Get endpoint with optional API key header
   * @param {string} line - The train line
   * @param {string} apiKey - Optional API key
   * @returns {object} Object with url and headers
   */
  getEndpointConfig(line, apiKey = null) {
    const url = this.getEndpointForLine(line);
    const headers = {};

    if (apiKey) {
      headers[this.config.metadata.api_key_header] = apiKey;
    }

    return { url, headers };
  }

  /**
   * Group lines by their feed
   * @returns {object} Object mapping feed groups to their lines
   */
  getLinesByFeed() {
    const result = {};
    for (const feedGroup of this.getAllFeedGroups()) {
      result[feedGroup] = this.getLinesInFeed(feedGroup);
    }
    return result;
  }

  /**
   * Search for lines by color
   * @param {string} color - Hex color code (e.g., '#EE352E')
   * @returns {Array<string>} Lines with this color
   */
  getLinesByColor(color) {
    const lines = [];
    for (const [line, lineColor] of Object.entries(this.config.line_colors)) {
      if (lineColor.toUpperCase() === color.toUpperCase()) {
        lines.push(line);
      }
    }
    return lines;
  }
}

// Create singleton instance
const mapper = new MTAFeedMapper();

// Export both the class and the singleton instance
module.exports = mapper;
module.exports.MTAFeedMapper = MTAFeedMapper;

// Export individual functions for convenience
module.exports.getEndpointForLine = mapper.getEndpointForLine.bind(mapper);
module.exports.getFeedGroupForLine = mapper.getFeedGroupForLine.bind(mapper);
module.exports.getAllLines = mapper.getAllLines.bind(mapper);
module.exports.getLinesInFeed = mapper.getLinesInFeed.bind(mapper);
module.exports.isValidLine = mapper.isValidLine.bind(mapper);
module.exports.getLineColor = mapper.getLineColor.bind(mapper);
module.exports.getFeedInfo = mapper.getFeedInfo.bind(mapper);
module.exports.getAllFeedGroups = mapper.getAllFeedGroups.bind(mapper);
module.exports.getBaseUrl = mapper.getBaseUrl.bind(mapper);
module.exports.getMetadata = mapper.getMetadata.bind(mapper);
module.exports.getEndpointConfig = mapper.getEndpointConfig.bind(mapper);
module.exports.getLinesByFeed = mapper.getLinesByFeed.bind(mapper);
module.exports.getLinesByColor = mapper.getLinesByColor.bind(mapper);
