const http = require('http');
const url = require('url');
const GtfsRealtimeBindings = require('gtfs-realtime-bindings');
const fetch = require('node-fetch');
const feedMapper = require('./lib/mta-feed-mapper');
require('dotenv').config();

const PORT = process.env.PORT || 3000;

// Comprehensive station list with coordinates
const STATIONS = {
  // L Train
  'L01': { name: '8 Av', line: 'L', lat: 40.7392, lon: -74.0025 },
  'L02': { name: '6 Av', line: 'L', lat: 40.7378, lon: -73.9963 },
  'L03': { name: 'Union Sq - 14 St', line: 'L', lat: 40.7346, lon: -73.9902 },
  'L05': { name: '3 Av', line: 'L', lat: 40.7326, lon: -73.9856 },
  'L06': { name: '1 Av', line: 'L', lat: 40.7308, lon: -73.9813 },
  'L08': { name: 'Bedford Av', line: 'L', lat: 40.7170, lon: -73.9565 },
  'L10': { name: 'Lorimer St', line: 'L', lat: 40.7128, lon: -73.9515 },
  'L11': { name: 'Graham Av', line: 'L', lat: 40.7140, lon: -73.9440 },
  'L12': { name: 'Grand St', line: 'L', lat: 40.7118, lon: -73.9400 },
  'L13': { name: 'Montrose Av', line: 'L', lat: 40.7072, lon: -73.9397 },
  'L14': { name: 'Morgan Av', line: 'L', lat: 40.7063, lon: -73.9333 },
  'L15': { name: 'Jefferson St', line: 'L', lat: 40.7063, lon: -73.9224 },
  'L16': { name: 'DeKalb Av', line: 'L', lat: 40.7036, lon: -73.9182 },
  'L17': { name: 'Myrtle-Wyckoff Avs', line: 'L', lat: 40.6995, lon: -73.9115 },
  'L19': { name: 'Halsey St', line: 'L', lat: 40.6955, lon: -73.9047 },
  'L20': { name: 'Wilson Av', line: 'L', lat: 40.6889, lon: -73.9041 },
  'L21': { name: 'Bushwick Av-Aberdeen St', line: 'L', lat: 40.6825, lon: -73.9053 },
  'L22': { name: 'Broadway Jct', line: 'L', lat: 40.6783, lon: -73.9052 },
  'L24': { name: 'Atlantic Av', line: 'L', lat: 40.6754, lon: -73.9030 },
  'L25': { name: 'Sutter Av', line: 'L', lat: 40.6692, lon: -73.9013 },
  'L26': { name: 'Livonia Av', line: 'L', lat: 40.6640, lon: -73.9002 },
  'L27': { name: 'New Lots Av', line: 'L', lat: 40.6587, lon: -73.8989 },
  'L28': { name: 'East 105 St', line: 'L', lat: 40.6502, lon: -73.8993 },
  'L29': { name: 'Canarsie-Rockaway Pkwy', line: 'L', lat: 40.6460, lon: -73.9016 },

  // G Train
  'G22': { name: 'Court Sq', line: 'G', lat: 40.7465, lon: -73.9457 },
  'G24': { name: '21 St', line: 'G', lat: 40.7441, lon: -73.9496 },
  'G26': { name: 'Greenpoint Av', line: 'G', lat: 40.7314, lon: -73.9540 },
  'G28': { name: 'Nassau Av', line: 'G', lat: 40.7243, lon: -73.9514 },
  'G29': { name: 'Metropolitan Av', line: 'G', lat: 40.7120, lon: -73.9514 },
  'G30': { name: 'Broadway', line: 'G', lat: 40.7062, lon: -73.9503 },
  'G31': { name: 'Flushing Av', line: 'G', lat: 40.7004, lon: -73.9508 },
  'G32': { name: 'Myrtle-Willoughby Avs', line: 'G', lat: 40.6941, lon: -73.9492 },
  'G33': { name: 'Bedford-Nostrand Avs', line: 'G', lat: 40.6896, lon: -73.9537 },
  'G34': { name: 'Classon Av', line: 'G', lat: 40.6885, lon: -73.9600 },
  'G35': { name: 'Clinton-Washington Avs', line: 'G', lat: 40.6838, lon: -73.9665 },
  'G36': { name: 'Fulton St', line: 'G', lat: 40.6875, lon: -73.9756 },

  // 1/2/3 Line Stations (Broadway-7th Ave)
  '101': { name: 'Van Cortlandt Park-242 St', line: '1', lat: 40.8897, lon: -73.8986 },
  '103': { name: '238 St', line: '1', lat: 40.8848, lon: -73.9001 },
  '104': { name: '231 St', line: '1', lat: 40.8783, lon: -73.9048 },
  '106': { name: 'Marble Hill-225 St', line: '1', lat: 40.8744, lon: -73.9097 },
  '107': { name: '215 St', line: '1', lat: 40.8694, lon: -73.9152 },
  '108': { name: '207 St', line: '1', lat: 40.8648, lon: -73.9186 },
  '109': { name: 'Dyckman St', line: '1', lat: 40.8608, lon: -73.9271 },
  '110': { name: '191 St', line: '1', lat: 40.8551, lon: -73.9294 },
  '111': { name: '181 St', line: '1', lat: 40.8498, lon: -73.9338 },
  '112': { name: '168 St', line: '1', lat: 40.8400, lon: -73.9400 },
  '113': { name: '157 St', line: '1', lat: 40.8342, lon: -73.9444 },
  '114': { name: '145 St', line: '1', lat: 40.8263, lon: -73.9502 },
  '115': { name: '137 St-City College', line: '1', lat: 40.8221, lon: -73.9537 },
  '116': { name: '125 St', line: '1', lat: 40.8153, lon: -73.9584 },
  '117': { name: '116 St-Columbia University', line: '1', lat: 40.8077, lon: -73.9640 },
  '118': { name: 'Cathedral Pkwy-110 St', line: '1', lat: 40.8037, lon: -73.9665 },
  '119': { name: '103 St', line: '1', lat: 40.7990, lon: -73.9681 },
  '120': { name: '96 St', line: '1/2/3', lat: 40.7937, lon: -73.9724 },
  '121': { name: '86 St', line: '1', lat: 40.7886, lon: -73.9759 },
  '122': { name: '79 St', line: '1', lat: 40.7839, lon: -73.9799 },
  '123': { name: '72 St', line: '1/2/3', lat: 40.7782, lon: -73.9819 },
  '124': { name: '66 St-Lincoln Center', line: '1', lat: 40.7734, lon: -73.9826 },
  '125': { name: '59 St-Columbus Circle', line: '1/A/B/C/D', lat: 40.7683, lon: -73.9819 },
  '126': { name: '50 St', line: '1', lat: 40.7616, lon: -73.9838 },
  '127': { name: 'Times Sq-42 St', line: '1/2/3', lat: 40.7548, lon: -73.9871 },
  '128': { name: '34 St-Penn Station', line: '1/2/3', lat: 40.7506, lon: -73.9916 },
  '129': { name: '28 St', line: '1', lat: 40.7476, lon: -73.9930 },
  '130': { name: '23 St', line: '1', lat: 40.7430, lon: -73.9958 },
  '131': { name: '18 St', line: '1', lat: 40.7400, lon: -73.9979 },
  '132': { name: '14 St', line: '1/2/3', lat: 40.7374, lon: -74.0006 },
  '133': { name: 'Christopher St-Sheridan Sq', line: '1', lat: 40.7339, lon: -74.0027 },
  '134': { name: 'Houston St', line: '1', lat: 40.7283, lon: -74.0053 },
  '135': { name: 'Canal St', line: '1', lat: 40.7220, lon: -74.0062 },
  '136': { name: 'Franklin St', line: '1', lat: 40.7191, lon: -74.0067 },
  '137': { name: 'Chambers St', line: '1/2/3', lat: 40.7155, lon: -74.0093 },
  '138': { name: 'WTC Cortlandt', line: '1', lat: 40.7115, lon: -74.0121 },
  '139': { name: 'Rector St', line: '1', lat: 40.7073, lon: -74.0134 },
  '140': { name: 'South Ferry', line: '1', lat: 40.7020, lon: -74.0131 },

  // 2/3 Line Additional Stations
  '201': { name: 'Wakefield-241 St', line: '2', lat: 40.9031, lon: -73.8506 },
  '204': { name: 'Nereid Av', line: '2', lat: 40.8983, lon: -73.8543 },
  '205': { name: '233 St', line: '2', lat: 40.8931, lon: -73.8577 },
  '206': { name: '225 St', line: '2', lat: 40.8882, lon: -73.8605 },
  '207': { name: '219 St', line: '2', lat: 40.8836, lon: -73.8627 },
  '208': { name: 'Gun Hill Rd', line: '2', lat: 40.8779, lon: -73.8660 },
  '209': { name: 'Burke Av', line: '2', lat: 40.8716, lon: -73.8670 },
  '210': { name: 'Allerton Av', line: '2', lat: 40.8654, lon: -73.8673 },
  '211': { name: 'Pelham Pkwy', line: '2', lat: 40.8575, lon: -73.8679 },
  '212': { name: 'Bronx Park East', line: '2', lat: 40.8484, lon: -73.8685 },
  '213': { name: 'E 180 St', line: '2', lat: 40.8417, lon: -73.8734 },
  '214': { name: 'West Farms Sq-E Tremont Av', line: '2', lat: 40.8403, lon: -73.8802 },
  '215': { name: '174 St', line: '2', lat: 40.8374, lon: -73.8878 },
  '216': { name: 'Freeman St', line: '2', lat: 40.8298, lon: -73.8916 },
  '217': { name: 'Simpson St', line: '2', lat: 40.8246, lon: -73.8930 },
  '218': { name: 'Intervale Av', line: '2', lat: 40.8221, lon: -73.8969 },
  '219': { name: 'Prospect Av', line: '2', lat: 40.8193, lon: -73.9017 },
  '220': { name: 'Jackson Av', line: '2', lat: 40.8163, lon: -73.9077 },
  '221': { name: '3 Av-149 St', line: '2', lat: 40.8162, lon: -73.9177 },
  '224': { name: 'Park Pl', line: '2/3', lat: 40.7133, lon: -74.0086 },
  '225': { name: 'Fulton St', line: '2/3', lat: 40.7102, lon: -74.0097 },
  '226': { name: 'Wall St', line: '2/3', lat: 40.7073, lon: -74.0091 },

  // 4/5/6 Line Stations (Lexington Ave)
  '401': { name: 'Woodlawn', line: '4', lat: 40.8862, lon: -73.8780 },
  '405': { name: 'Mosholu Pkwy', line: '4', lat: 40.8797, lon: -73.8841 },
  '406': { name: 'Bedford Park Blvd-Lehman College', line: '4', lat: 40.8734, lon: -73.8903 },
  '407': { name: 'Kingsbridge Rd', line: '4', lat: 40.8668, lon: -73.8973 },
  '408': { name: 'Fordham Rd', line: '4', lat: 40.8621, lon: -73.9011 },
  '409': { name: '183 St', line: '4', lat: 40.8583, lon: -73.9032 },
  '410': { name: 'Burnside Av', line: '4', lat: 40.8534, lon: -73.9075 },
  '411': { name: '176 St', line: '4', lat: 40.8479, lon: -73.9119 },
  '412': { name: 'Mt Eden Av', line: '4', lat: 40.8444, lon: -73.9148 },
  '413': { name: '170 St', line: '4', lat: 40.8399, lon: -73.9175 },
  '414': { name: '167 St', line: '4', lat: 40.8350, lon: -73.9214 },
  '415': { name: '161 St-Yankee Stadium', line: '4', lat: 40.8278, lon: -73.9255 },
  '416': { name: '149 St-Grand Concourse', line: '4', lat: 40.8185, lon: -73.9273 },
  '418': { name: '138 St-Grand Concourse', line: '4', lat: 40.8132, lon: -73.9298 },
  '419': { name: '125 St', line: '4/5/6', lat: 40.8045, lon: -73.9377 },
  '621': { name: '86 St', line: '4/5/6', lat: 40.7794, lon: -73.9557 },
  '622': { name: '77 St', line: '6', lat: 40.7738, lon: -73.9596 },
  '623': { name: '68 St-Hunter College', line: '6', lat: 40.7683, lon: -73.9640 },
  '624': { name: '59 St', line: '4/5/6', lat: 40.7625, lon: -73.9676 },
  '625': { name: '51 St', line: '6', lat: 40.7572, lon: -73.9718 },
  '626': { name: 'Grand Central-42 St', line: '4/5/6', lat: 40.7518, lon: -73.9766 },
  '627': { name: '33 St', line: '6', lat: 40.7460, lon: -73.9821 },
  '628': { name: '28 St', line: '6', lat: 40.7430, lon: -73.9845 },
  '629': { name: '23 St', line: '6', lat: 40.7397, lon: -73.9868 },
  '630': { name: '14 St-Union Sq', line: '4/5/6', lat: 40.7352, lon: -73.9912 },
  '631': { name: 'Astor Pl', line: '6', lat: 40.7301, lon: -73.9908 },
  '632': { name: 'Bleecker St', line: '6', lat: 40.7258, lon: -73.9945 },
  '633': { name: 'Spring St', line: '6', lat: 40.7222, lon: -73.9973 },
  '634': { name: 'Canal St', line: '6', lat: 40.7188, lon: -74.0001 },
  '635': { name: 'Brooklyn Bridge-City Hall', line: '4/5/6', lat: 40.7130, lon: -74.0043 },

  // A/C/E Line Stations (8th Ave)
  'A02': { name: 'Inwood-207 St', line: 'A', lat: 40.8680, lon: -73.9197 },
  'A03': { name: 'Dyckman St', line: 'A', lat: 40.8653, lon: -73.9273 },
  'A05': { name: '190 St', line: 'A', lat: 40.8590, lon: -73.9338 },
  'A06': { name: '181 St', line: 'A', lat: 40.8512, lon: -73.9374 },
  'A07': { name: '175 St', line: 'A', lat: 40.8475, lon: -73.9399 },
  'A09': { name: '168 St', line: 'A/C', lat: 40.8408, lon: -73.9398 },
  'A10': { name: '163 St-Amsterdam Av', line: 'C', lat: 40.8362, lon: -73.9398 },
  'A11': { name: '155 St', line: 'C', lat: 40.8302, lon: -73.9415 },
  'A12': { name: '145 St', line: 'A/C', lat: 40.8243, lon: -73.9440 },
  'A15': { name: '135 St', line: 'C', lat: 40.8174, lon: -73.9473 },
  'A16': { name: '125 St', line: 'A/C', lat: 40.8115, lon: -73.9520 },
  'A17': { name: '116 St', line: 'C', lat: 40.8050, lon: -73.9544 },
  'A18': { name: 'Cathedral Pkwy-110 St', line: 'C', lat: 40.8003, lon: -73.9583 },
  'A19': { name: '103 St', line: 'C', lat: 40.7959, lon: -73.9613 },
  'A20': { name: '96 St', line: 'A/C', lat: 40.7914, lon: -73.9722 },
  'A21': { name: '86 St', line: 'A/C', lat: 40.7858, lon: -73.9763 },
  'A22': { name: '81 St-Museum of Natural History', line: 'A/C', lat: 40.7813, lon: -73.9720 },
  'A24': { name: '72 St', line: 'A/C', lat: 40.7758, lon: -73.9818 },
  'A25': { name: '59 St-Columbus Circle', line: 'A/B/C/D', lat: 40.7683, lon: -73.9819 },
  'A27': { name: '50 St', line: 'A/C/E', lat: 40.7620, lon: -73.9856 },
  'A28': { name: '42 St-Port Authority', line: 'A/C/E', lat: 40.7577, lon: -73.9897 },
  'A31': { name: '34 St-Penn Station', line: 'A/C/E', lat: 40.7521, lon: -73.9933 },
  'A32': { name: '23 St', line: 'A/C/E', lat: 40.7453, lon: -73.9985 },
  'A33': { name: '14 St', line: 'A/C/E', lat: 40.7404, lon: -74.0015 },
  'A34': { name: 'W 4 St-Wash Sq', line: 'A/C/E', lat: 40.7323, lon: -74.0004 },
  'A36': { name: 'Spring St', line: 'A/C/E', lat: 40.7262, lon: -74.0037 },
  'A38': { name: 'Canal St', line: 'A/C/E', lat: 40.7207, lon: -74.0056 },
  'A40': { name: 'Chambers St', line: 'A/C', lat: 40.7142, lon: -74.0089 },
  'A41': { name: 'Fulton St', line: 'A/C', lat: 40.7104, lon: -74.0071 },

  // B/D/F/M Line Stations (6th Ave)
  'B04': { name: 'Bedford Park Blvd', line: 'B/D', lat: 40.8731, lon: -73.8873 },
  'B06': { name: 'Kingsbridge Rd', line: 'B/D', lat: 40.8670, lon: -73.8939 },
  'B08': { name: 'Fordham Rd', line: 'B/D', lat: 40.8622, lon: -73.8975 },
  'B10': { name: '182-183 Sts', line: 'B/D', lat: 40.8564, lon: -73.9004 },
  'B12': { name: 'Tremont Av', line: 'B/D', lat: 40.8502, lon: -73.9052 },
  'B13': { name: '174-175 Sts', line: 'B/D', lat: 40.8456, lon: -73.9102 },
  'B14': { name: '170 St', line: 'B/D', lat: 40.8403, lon: -73.9137 },
  'B15': { name: '167 St', line: 'B/D', lat: 40.8338, lon: -73.9185 },
  'B16': { name: '161 St-Yankee Stadium', line: 'B/D', lat: 40.8275, lon: -73.9254 },
  'B17': { name: '155 St', line: 'B/D', lat: 40.8303, lon: -73.9186 },
  'B18': { name: '145 St', line: 'B/D', lat: 40.8243, lon: -73.9361 },
  'B19': { name: '135 St', line: 'B/D', lat: 40.8174, lon: -73.9400 },
  'B20': { name: '125 St', line: 'B/D', lat: 40.8115, lon: -73.9478 },
  'B21': { name: '116 St', line: 'B/D', lat: 40.8050, lon: -73.9540 },
  'B22': { name: 'Cathedral Pkwy-110 St', line: 'B/D', lat: 40.8003, lon: -73.9579 },
  'B23': { name: '103 St', line: 'B/D', lat: 40.7959, lon: -73.9611 },
  'D17': { name: '7 Av', line: 'B/D/E', lat: 40.7629, lon: -73.9811 },
  'D18': { name: '47-50 Sts-Rockefeller Ctr', line: 'B/D/F/M', lat: 40.7586, lon: -73.9776 },
  'D19': { name: '42 St-Bryant Park', line: 'B/D/F/M', lat: 40.7546, lon: -73.9841 },
  'D20': { name: '34 St-Herald Sq', line: 'B/D/F/M', lat: 40.7496, lon: -73.9877 },
  'D21': { name: '23 St', line: 'F/M', lat: 40.7428, lon: -73.9926 },
  'D22': { name: '14 St', line: 'F/M', lat: 40.7393, lon: -73.9960 },
  'F14': { name: 'W 4 St-Wash Sq', line: 'A/C/E/B/D/F/M', lat: 40.7323, lon: -74.0004 },
  'F15': { name: 'Broadway-Lafayette St', line: 'B/D/F/M', lat: 40.7255, lon: -73.9960 },
  'F16': { name: 'Grand St', line: 'B/D', lat: 40.7186, lon: -73.9939 },

  // E/M Line Stations (Queens Blvd/6th Ave)
  'E01': { name: 'Lexington Av/53 St', line: 'E/M', lat: 40.7575, lon: -73.9690 },
  'E02': { name: '5 Av/53 St', line: 'E/M', lat: 40.7605, lon: -73.9752 },
  'E03': { name: '42 St-Port Authority', line: 'A/C/E', lat: 40.7573, lon: -73.9898 },
  'E04': { name: '34 St-Penn Station', line: 'A/C/E', lat: 40.7520, lon: -73.9930 },
  'E05': { name: '23 St', line: 'E/C', lat: 40.7454, lon: -73.9979 },
  'E06': { name: '14 St', line: 'A/C/E/L', lat: 40.7407, lon: -74.0006 },
  'E07': { name: 'W 4 St-Wash Sq', line: 'A/C/E/B/D/F/M', lat: 40.7323, lon: -74.0004 },
  'E08': { name: 'Spring St', line: 'E/C', lat: 40.7263, lon: -74.0039 },
  'E09': { name: 'Canal St', line: 'A/C/E', lat: 40.7210, lon: -74.0059 },

  // N/Q/R/W Line Stations (Broadway/Lexington)
  'R11': { name: '57 St-7 Av', line: 'N/Q/R/W', lat: 40.7645, lon: -73.9807 },
  'R13': { name: '49 St', line: 'N/Q/R/W', lat: 40.7600, lon: -73.9843 },
  'R14': { name: 'Times Sq-42 St', line: 'N/Q/R/W', lat: 40.7557, lon: -73.9866 },
  'R15': { name: '34 St-Herald Sq', line: 'N/Q/R/W', lat: 40.7500, lon: -73.9874 },
  'R16': { name: '28 St', line: 'N/R/W', lat: 40.7455, lon: -73.9880 },
  'R17': { name: '23 St', line: 'N/R/W', lat: 40.7416, lon: -73.9896 },
  'R18': { name: '14 St-Union Sq', line: 'N/Q/R/W', lat: 40.7352, lon: -73.9907 },
  'R19': { name: '8 St-NYU', line: 'N/R/W', lat: 40.7303, lon: -73.9925 },
  'R20': { name: 'Prince St', line: 'N/R/W', lat: 40.7245, lon: -73.9973 },
  'R21': { name: 'Canal St', line: 'N/Q/R/W', lat: 40.7189, lon: -74.0010 },
  'R22': { name: 'City Hall', line: 'N/R/W', lat: 40.7133, lon: -74.0067 },
  'R23': { name: 'Cortlandt St', line: 'N/R/W', lat: 40.7103, lon: -74.0117 },
  'R25': { name: 'Whitehall St-South Ferry', line: 'N/R/W', lat: 40.7032, lon: -74.0129 },

  // 7 Line Stations (Flushing)
  '701': { name: 'Flushing-Main St', line: '7', lat: 40.7596, lon: -73.8303 },
  '702': { name: 'Mets-Willets Point', line: '7', lat: 40.7546, lon: -73.8456 },
  '705': { name: '111 St', line: '7', lat: 40.7516, lon: -73.8553 },
  '706': { name: '103 St-Corona Plaza', line: '7', lat: 40.7497, lon: -73.8628 },
  '707': { name: 'Junction Blvd', line: '7', lat: 40.7493, lon: -73.8691 },
  '708': { name: '90 St-Elmhurst Av', line: '7', lat: 40.7481, lon: -73.8764 },
  '709': { name: '82 St-Jackson Hts', line: '7', lat: 40.7477, lon: -73.8837 },
  '710': { name: '74 St-Broadway', line: '7', lat: 40.7466, lon: -73.8914 },
  '711': { name: '69 St', line: '7', lat: 40.7463, lon: -73.8964 },
  '712': { name: 'Woodside-61 St', line: '7', lat: 40.7454, lon: -73.9025 },
  '713': { name: '52 St', line: '7', lat: 40.7444, lon: -73.9124 },
  '714': { name: '46 St', line: '7', lat: 40.7435, lon: -73.9182 },
  '715': { name: '40 St', line: '7', lat: 40.7443, lon: -73.9240 },
  '716': { name: '33 St', line: '7', lat: 40.7448, lon: -73.9301 },
  '718': { name: 'Queensboro Plaza', line: '7', lat: 40.7502, lon: -73.9401 },
  '719': { name: '5 Av', line: '7', lat: 40.7536, lon: -73.9815 },
  '720': { name: 'Grand Central-42 St', line: '7', lat: 40.7516, lon: -73.9768 },
  '721': { name: '34 St-Hudson Yards', line: '7', lat: 40.7558, lon: -74.0012 }
};

// Calculate distance between two coordinates in miles
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

// Find closest station to given coordinates
function findClosestStation(lat, lon) {
  let closestStation = null;
  let minDistance = Infinity;
  let closestStopId = null;

  for (const [stopId, station] of Object.entries(STATIONS)) {
    const distance = calculateDistance(lat, lon, station.lat, station.lon);
    if (distance < minDistance) {
      minDistance = distance;
      closestStation = station;
      closestStopId = stopId;
    }
  }

  return { stopId: closestStopId, station: closestStation, distance: minDistance };
}

// Find multiple nearby stations within a radius
function findNearbyStations(lat, lon, radiusMiles = 0.4, maxStations = 5) {
  const nearbyStations = [];

  for (const [stopId, station] of Object.entries(STATIONS)) {
    const distance = calculateDistance(lat, lon, station.lat, station.lon);
    if (distance <= radiusMiles) {
      nearbyStations.push({ stopId, station, distance });
    }
  }

  // Sort by distance and limit to maxStations
  nearbyStations.sort((a, b) => a.distance - b.distance);
  return nearbyStations.slice(0, maxStations);
}

// Define terminal stations for each line
const LINE_TERMINALS = {
  'L': {
    northbound: '8 Av',
    southbound: 'Canarsie-Rockaway Pkwy'
  },
  'G': {
    northbound: 'Court Sq',
    southbound: 'Church Av'
  },
  'A': {
    northbound: 'Inwood-207 St',
    southbound: 'Far Rockaway/Rockaway Park'
  },
  'C': {
    northbound: '168 St',
    southbound: 'Euclid Av'
  },
  'E': {
    northbound: 'Jamaica Center',
    southbound: 'World Trade Center'
  },
  'B': {
    northbound: 'Bedford Park Blvd',
    southbound: 'Brighton Beach'
  },
  'D': {
    northbound: 'Norwood-205 St',
    southbound: 'Coney Island-Stillwell Av'
  },
  'F': {
    northbound: 'Jamaica-179 St',
    southbound: 'Coney Island-Stillwell Av'
  },
  'M': {
    northbound: 'Forest Hills-71 Av',
    southbound: 'Middle Village-Metropolitan Av'
  },
  'N': {
    northbound: 'Astoria-Ditmars Blvd',
    southbound: 'Coney Island-Stillwell Av'
  },
  'Q': {
    northbound: '96 St',
    southbound: 'Coney Island-Stillwell Av'
  },
  'R': {
    northbound: 'Forest Hills-71 Av',
    southbound: 'Bay Ridge-95 St'
  },
  'W': {
    northbound: 'Astoria-Ditmars Blvd',
    southbound: 'Whitehall St'
  },
  '1': {
    northbound: 'Van Cortlandt Park-242 St',
    southbound: 'South Ferry'
  },
  '2': {
    northbound: 'Wakefield-241 St',
    southbound: 'Flatbush Av-Brooklyn College'
  },
  '3': {
    northbound: 'Harlem-148 St',
    southbound: 'New Lots Av'
  },
  '4': {
    northbound: 'Woodlawn',
    southbound: 'Crown Hts-Utica Av'
  },
  '5': {
    northbound: 'Eastchester-Dyre Av',
    southbound: 'Flatbush Av-Brooklyn College'
  },
  '6': {
    northbound: 'Pelham Bay Park',
    southbound: 'Brooklyn Bridge-City Hall'
  },
  '7': {
    northbound: 'Flushing-Main St',
    southbound: '34 St-Hudson Yards'
  }
};

// Get train arrivals for a specific stop
async function getTrainArrivals(stopId, lineName) {
  try {
    const station = STATIONS[stopId];
    if (!station) {
      throw new Error('Invalid stop ID');
    }

    // Extract all lines that serve this station
    const lines = station.line.split('/');

    const now = Date.now() / 1000;
    const arrivalsByDirection = {
      northbound: [],
      southbound: []
    };

    // Fetch data for each line that serves this station
    for (const line of lines) {
      try {
        const feedUrl = feedMapper.getEndpointForLine(line);

        const headers = {};
        if (process.env.MTA_API_KEY) {
          headers['x-api-key'] = process.env.MTA_API_KEY;
        }

        const response = await fetch(feedUrl, { headers });
        if (!response.ok) {
          console.error(`HTTP error for line ${line}! status: ${response.status}`);
          continue; // Skip this line and try the next one
        }

        const buffer = await response.arrayBuffer();
        const feed = GtfsRealtimeBindings.transit_realtime.FeedMessage.decode(
          new Uint8Array(buffer)
        );

        // Get terminal station names for this line
        const terminals = LINE_TERMINALS[line] || {
          northbound: 'Northbound',
          southbound: 'Southbound'
        };

        feed.entity.forEach(entity => {
          if (entity.tripUpdate && entity.tripUpdate.stopTimeUpdate) {
            // Get the route ID from the trip
            const routeId = entity.tripUpdate.trip?.routeId;

            entity.tripUpdate.stopTimeUpdate.forEach(stopTime => {
              // Match the stop ID (with directional suffix)
              if (stopTime.stopId && stopTime.stopId.startsWith(stopId)) {
                const arrivalTime = stopTime.arrival?.time || stopTime.departure?.time;
                if (arrivalTime) {
                  const arrivalTimestamp = parseInt(arrivalTime.low || arrivalTime);
                  if (arrivalTimestamp > now) {
                    const minutesAway = Math.floor((arrivalTimestamp - now) / 60);
                    const isNorthbound = stopTime.stopId.endsWith('N');
                    const direction = isNorthbound ? 'northbound' : 'southbound';
                    const destinationName = isNorthbound ? terminals.northbound : terminals.southbound;

                    // Use routeId if available, otherwise use the line we're fetching
                    const trainLine = routeId || line;

                    const arrivalInfo = {
                      line: trainLine,
                      station: station.name,
                      direction: `to ${destinationName}`,
                      minutesAway: minutesAway,
                      arrivalTime: new Date(arrivalTimestamp * 1000)
                    };

                    arrivalsByDirection[direction].push(arrivalInfo);
                  }
                }
              }
            });
          }
        });
      } catch (lineError) {
        console.error(`Error fetching data for line ${line}:`, lineError.message);
        // Continue with next line
      }
    }

    // Sort by arrival time and limit to 6 per direction (increased from 2)
    arrivalsByDirection.northbound.sort((a, b) => a.minutesAway - b.minutesAway);
    arrivalsByDirection.southbound.sort((a, b) => a.minutesAway - b.minutesAway);

    return {
      northbound: arrivalsByDirection.northbound.slice(0, 6),
      southbound: arrivalsByDirection.southbound.slice(0, 6)
    };
  } catch (error) {
    console.error('Error fetching train data:', error.message);
    return { northbound: [], southbound: [] };
  }
}

function generateHTML() {
  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MTA Train Tracker</title>
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
      padding: 20px;
    }

    .container {
      max-width: 1200px;
      margin: 0 auto;
    }

    .header {
      text-align: center;
      margin-bottom: 30px;
    }

    .header h1 {
      font-size: 2.5em;
      margin-bottom: 10px;
    }

    .controls {
      background: rgba(255, 255, 255, 0.1);
      backdrop-filter: blur(10px);
      border-radius: 15px;
      padding: 25px;
      margin-bottom: 30px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }

    .control-section {
      margin-bottom: 20px;
    }

    .control-section:last-child {
      margin-bottom: 0;
    }

    .control-section h3 {
      margin-bottom: 15px;
      font-size: 1.2em;
    }

    .button-group {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    button {
      background: rgba(255, 255, 255, 0.9);
      color: #667eea;
      border: none;
      padding: 12px 24px;
      border-radius: 8px;
      font-size: 1em;
      font-weight: bold;
      cursor: pointer;
      transition: all 0.3s;
    }

    button:hover {
      background: white;
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }

    button:active {
      transform: translateY(0);
    }

    button.primary {
      background: #ff6b6b;
      color: white;
    }

    button.primary:hover {
      background: #ff5252;
    }

    select {
      padding: 10px 15px;
      border-radius: 8px;
      border: none;
      font-size: 1em;
      background: rgba(255, 255, 255, 0.9);
      color: #333;
      margin-right: 10px;
      min-width: 200px;
    }

    .results {
      background: rgba(255, 255, 255, 0.1);
      backdrop-filter: blur(10px);
      border-radius: 15px;
      padding: 25px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }

    .station-header {
      text-align: center;
      margin-bottom: 25px;
      padding-bottom: 15px;
      border-bottom: 2px solid rgba(255, 255, 255, 0.3);
    }

    .station-header h2 {
      font-size: 1.8em;
      margin-bottom: 5px;
    }

    .distance-info {
      font-size: 0.9em;
      opacity: 0.8;
    }

    .directions {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 20px;
      margin-top: 20px;
    }

    .direction-card {
      background: rgba(255, 255, 255, 0.05);
      border-radius: 10px;
      padding: 20px;
    }

    .direction-card h3 {
      margin-bottom: 15px;
      font-size: 1.3em;
      text-align: center;
    }

    .train-arrival {
      background: rgba(255, 255, 255, 0.1);
      padding: 15px;
      border-radius: 8px;
      margin-bottom: 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .train-line-badge {
      display: inline-block;
      background: white;
      color: #333;
      font-weight: bold;
      padding: 5px 12px;
      border-radius: 5px;
      margin-right: 10px;
    }

    .minutes {
      font-size: 1.5em;
      font-weight: bold;
    }

    .no-trains {
      text-align: center;
      padding: 20px;
      opacity: 0.7;
    }

    .loading {
      text-align: center;
      padding: 40px;
      font-size: 1.2em;
    }

    .error {
      background: rgba(255, 0, 0, 0.2);
      padding: 15px;
      border-radius: 8px;
      text-align: center;
    }

    /* Modal Styles */
    .modal {
      display: none;
      position: fixed;
      z-index: 1000;
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      background-color: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(5px);
    }

    .modal-content {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      margin: 10% auto;
      padding: 30px;
      border-radius: 15px;
      width: 90%;
      max-width: 500px;
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
    }

    .close {
      color: white;
      float: right;
      font-size: 28px;
      font-weight: bold;
      cursor: pointer;
      opacity: 0.7;
      transition: opacity 0.3s;
    }

    .close:hover {
      opacity: 1;
    }

    .modal h2 {
      margin-bottom: 20px;
      color: white;
    }

    .search-container {
      position: relative;
      margin-bottom: 20px;
    }

    .search-input {
      width: 100%;
      padding: 15px;
      border: none;
      border-radius: 8px;
      font-size: 1em;
      box-sizing: border-box;
    }

    .autocomplete-results {
      position: absolute;
      top: 100%;
      left: 0;
      right: 0;
      background: white;
      border-radius: 8px;
      margin-top: 5px;
      max-height: 300px;
      overflow-y: auto;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
      z-index: 1001;
    }

    .autocomplete-item {
      padding: 12px 15px;
      cursor: pointer;
      color: #333;
      border-bottom: 1px solid #eee;
    }

    .autocomplete-item:hover {
      background-color: #f0f0f0;
    }

    .autocomplete-item:last-child {
      border-bottom: none;
    }

    .modal-buttons {
      display: flex;
      gap: 10px;
      margin-top: 20px;
    }

    .modal-buttons button {
      flex: 1;
    }

    @media (max-width: 768px) {
      .header h1 {
        font-size: 1.8em;
      }
      .button-group {
        flex-direction: column;
      }
      button, select {
        width: 100%;
      }
      .modal-content {
        margin: 20% auto;
        width: 95%;
        padding: 20px;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🚇 MTA Train Tracker</h1>
      <p>Real-time subway arrivals</p>
    </div>

    <div class="controls">
      <div class="control-section">
        <h3>🏠 Home Location</h3>
        <div class="button-group">
          <button class="primary" onclick="useHomeLocation()">Check Home Station</button>
          <button onclick="setHomeLocation()">Set New Home</button>
        </div>
        <div id="homeLocationDisplay" style="margin-top: 10px; opacity: 0.8; font-size: 0.9em;">
          <!-- Home location will be displayed here -->
        </div>
      </div>

      <div class="control-section">
        <h3>💼 Work Location</h3>
        <div class="button-group">
          <button class="primary" onclick="useWorkLocation()">Check Work Station</button>
          <button onclick="setWorkLocation()">Set New Work</button>
        </div>
        <div id="workLocationDisplay" style="margin-top: 10px; opacity: 0.8; font-size: 0.9em;">
          <!-- Work location will be displayed here -->
        </div>
      </div>

      <div class="control-section">
        <h3>📍 Find Nearest Station</h3>
        <div class="button-group">
          <button onclick="useMyLocation()">Use My Current Location</button>
        </div>
      </div>

      <div class="control-section">
        <h3>🎯 Manual Selection</h3>
        <div class="button-group">
          <select id="lineSelect" onchange="updateStationsByLine()">
            <option value="">Select a train line...</option>
            <option value="L">L Train</option>
            <option value="G">G Train</option>
            <option value="A">A Train</option>
            <option value="C">C Train</option>
            <option value="E">E Train</option>
            <option value="B">B Train</option>
            <option value="D">D Train</option>
            <option value="F">F Train</option>
            <option value="M">M Train</option>
            <option value="N">N Train</option>
            <option value="Q">Q Train</option>
            <option value="R">R Train</option>
            <option value="W">W Train</option>
            <option value="J">J Train</option>
            <option value="Z">Z Train</option>
            <option value="1">1 Train</option>
            <option value="2">2 Train</option>
            <option value="3">3 Train</option>
            <option value="4">4 Train</option>
            <option value="5">5 Train</option>
            <option value="6">6 Train</option>
            <option value="7">7 Train</option>
          </select>
          <select id="stationSelect" disabled>
            <option value="">First select a line...</option>
          </select>
          <button onclick="selectStation()">Get Train Times</button>
        </div>
      </div>
    </div>

    <div id="results" class="results" style="display: none;">
      <div id="resultsContent"></div>
    </div>
  </div>

  <!-- Address Search Modal -->
  <div id="addressModal" class="modal">
    <div class="modal-content">
      <span class="close" onclick="closeAddressModal()">&times;</span>
      <h2 id="modalTitle">Set Location</h2>
      <div class="search-container">
        <input
          type="text"
          id="addressSearch"
          class="search-input"
          placeholder="Start typing an address..."
          autocomplete="off"
        />
        <div id="autocompleteResults" class="autocomplete-results" style="display: none;"></div>
      </div>
      <div class="modal-buttons">
        <button onclick="closeAddressModal()">Cancel</button>
      </div>
    </div>
  </div>

  <script>
    // Default home location: Lorimer St L Train Station
    const DEFAULT_HOME = {
      name: 'Lorimer St (L Train)',
      lat: 40.7128,
      lon: -73.9515
    };

    // Default work location: 640 5th Ave, NYC
    const DEFAULT_WORK = {
      name: '640 5th Ave, NYC',
      lat: 40.7564,
      lon: -73.9787
    };

    // All stations data for filtering
    const ALL_STATIONS = ${JSON.stringify(STATIONS)};

    // Initialize home location from localStorage or use default
    function getHomeLocation() {
      const saved = localStorage.getItem('homeLocation');
      if (saved) {
        return JSON.parse(saved);
      }
      return DEFAULT_HOME;
    }

    // Initialize work location from localStorage or use default
    function getWorkLocation() {
      const saved = localStorage.getItem('workLocation');
      if (saved) {
        return JSON.parse(saved);
      }
      return DEFAULT_WORK;
    }

    function setHomeLocationData(name, lat, lon) {
      const home = { name, lat, lon };
      localStorage.setItem('homeLocation', JSON.stringify(home));
      updateLocationDisplays();
      return home;
    }

    function setWorkLocationData(name, lat, lon) {
      const work = { name, lat, lon };
      localStorage.setItem('workLocation', JSON.stringify(work));
      updateLocationDisplays();
      return work;
    }

    function updateLocationDisplays() {
      const home = getHomeLocation();
      const work = getWorkLocation();
      const homeDisplay = document.getElementById('homeLocationDisplay');
      const workDisplay = document.getElementById('workLocationDisplay');
      homeDisplay.innerHTML = \`📍 Home: \${home.name}\`;
      workDisplay.innerHTML = \`📍 Work: \${work.name}\`;
    }

    // Use home location
    async function useHomeLocation() {
      const home = getHomeLocation();

      const resultsDiv = document.getElementById('results');
      const resultsContent = document.getElementById('resultsContent');

      resultsDiv.style.display = 'block';
      resultsContent.innerHTML = '<div class="loading">🏠 Finding nearby stations to home...</div>';

      try {
        const response = await fetch(\`/api/nearby?lat=\${home.lat}&lon=\${home.lon}\`);
        const data = await response.json();

        displayMultipleStations(data);
      } catch (error) {
        resultsContent.innerHTML = '<div class="error">Error fetching train data. Please try again.</div>';
      }
    }

    // Use work location
    async function useWorkLocation() {
      const work = getWorkLocation();

      const resultsDiv = document.getElementById('results');
      const resultsContent = document.getElementById('resultsContent');

      resultsDiv.style.display = 'block';
      resultsContent.innerHTML = '<div class="loading">💼 Finding nearby stations to work...</div>';

      try {
        const response = await fetch(\`/api/nearby?lat=\${work.lat}&lon=\${work.lon}\`);
        const data = await response.json();

        displayMultipleStations(data);
      } catch (error) {
        resultsContent.innerHTML = '<div class="error">Error fetching train data. Please try again.</div>';
      }
    }

    // Modal state
    let currentLocationMode = null; // 'home' or 'work'
    let searchTimeout = null;
    let selectedLocation = null;

    // Open address modal
    function openAddressModal(mode) {
      currentLocationMode = mode;
      const modal = document.getElementById('addressModal');
      const modalTitle = document.getElementById('modalTitle');
      const searchInput = document.getElementById('addressSearch');

      modalTitle.textContent = mode === 'home' ? 'Set Home Location' : 'Set Work Location';
      searchInput.value = '';
      selectedLocation = null;

      const autocompleteResults = document.getElementById('autocompleteResults');
      autocompleteResults.style.display = 'none';
      autocompleteResults.innerHTML = '';

      modal.style.display = 'block';
      searchInput.focus();
    }

    // Close address modal
    function closeAddressModal() {
      const modal = document.getElementById('addressModal');
      modal.style.display = 'none';
      currentLocationMode = null;
      selectedLocation = null;
    }

    // Handle address search with autocomplete (NYC only)
    async function handleAddressSearch(query) {
      if (query.length < 3) {
        document.getElementById('autocompleteResults').style.display = 'none';
        return;
      }

      try {
        // Limit search to New York City area
        const response = await fetch(\`https://nominatim.openstreetmap.org/search?format=json&q=\${encodeURIComponent(query)}, New York City&limit=5&countrycodes=us\`);
        const data = await response.json();

        const autocompleteResults = document.getElementById('autocompleteResults');

        // Filter results to only show NYC area (roughly within NYC bounds)
        const nycResults = data.filter(location => {
          const lat = parseFloat(location.lat);
          const lon = parseFloat(location.lon);
          // NYC approximate bounds
          return lat >= 40.4 && lat <= 41.0 && lon >= -74.3 && lon <= -73.7;
        });

        if (nycResults.length === 0) {
          autocompleteResults.innerHTML = '<div class="autocomplete-item">No NYC results found. Please search for addresses in New York City.</div>';
          autocompleteResults.style.display = 'block';
          return;
        }

        autocompleteResults.innerHTML = nycResults.map(location => \`
          <div class="autocomplete-item" onclick="selectAddress('\${location.display_name.replace(/'/g, "\\\\'")}', \${location.lat}, \${location.lon})">
            \${location.display_name}
          </div>
        \`).join('');

        autocompleteResults.style.display = 'block';
      } catch (error) {
        console.error('Error searching addresses:', error);
      }
    }

    // Select an address from autocomplete
    function selectAddress(displayName, lat, lon) {
      selectedLocation = {
        name: displayName,
        lat: parseFloat(lat),
        lon: parseFloat(lon)
      };

      // Set the location and close modal
      if (currentLocationMode === 'home') {
        setHomeLocationData(displayName, selectedLocation.lat, selectedLocation.lon);
        closeAddressModal();
        useHomeLocation();
      } else if (currentLocationMode === 'work') {
        setWorkLocationData(displayName, selectedLocation.lat, selectedLocation.lon);
        closeAddressModal();
        useWorkLocation();
      }
    }

    // Set new home location
    function setHomeLocation() {
      openAddressModal('home');
    }

    // Set new work location
    function setWorkLocation() {
      openAddressModal('work');
    }

    // Use current GPS location
    async function useMyLocation() {
      if (!navigator.geolocation) {
        alert('Geolocation is not supported by your browser');
        return;
      }

      const resultsDiv = document.getElementById('results');
      const resultsContent = document.getElementById('resultsContent');

      resultsDiv.style.display = 'block';
      resultsContent.innerHTML = '<div class="loading">📍 Getting your location...</div>';

      navigator.geolocation.getCurrentPosition(async (position) => {
        const lat = position.coords.latitude;
        const lon = position.coords.longitude;

        // Check if location is within NYC bounds
        const isInNYC = lat >= 40.4 && lat <= 41.0 && lon >= -74.3 && lon <= -73.7;

        if (!isInNYC) {
          // Show message and fallback to home location
          resultsContent.innerHTML = '<div class="info-message" style="padding: 20px; background-color: #fff3cd; border-left: 4px solid #ffc107; margin-bottom: 20px; border-radius: 4px;">I see you are outside of NY so instead, I will show you data for your Home location</div>';

          // Wait a moment for user to see the message, then load home location
          setTimeout(() => {
            useHomeLocation();
          }, 1500);
          return;
        }

        resultsContent.innerHTML = '<div class="loading">🔍 Finding nearest station...</div>';

        try {
          const response = await fetch(\`/api/nearest?lat=\${lat}&lon=\${lon}\`);
          const data = await response.json();

          displayResults(data);
        } catch (error) {
          resultsContent.innerHTML = '<div class="error">Error fetching train data. Please try again.</div>';
        }
      }, (error) => {
        resultsContent.innerHTML = '<div class="error">Unable to get your location. Please enable location services.</div>';
      });
    }

    // Update stations dropdown based on selected line
    function updateStationsByLine() {
      const lineSelect = document.getElementById('lineSelect');
      const stationSelect = document.getElementById('stationSelect');
      const selectedLine = lineSelect.value;

      if (!selectedLine) {
        stationSelect.disabled = true;
        stationSelect.innerHTML = '<option value="">First select a line...</option>';
        return;
      }

      // Filter stations by selected line
      const filteredStations = Object.entries(ALL_STATIONS)
        .filter(([stopId, station]) => {
          // Check if the station's line includes the selected line
          const lines = station.line.split('/');
          return lines.includes(selectedLine);
        })
        .sort((a, b) => a[1].name.localeCompare(b[1].name));

      if (filteredStations.length === 0) {
        stationSelect.disabled = true;
        stationSelect.innerHTML = '<option value="">No stations available for this line</option>';
        return;
      }

      // Populate station dropdown
      stationSelect.disabled = false;
      stationSelect.innerHTML = '<option value="">Select a station...</option>' +
        filteredStations.map(([stopId, station]) =>
          \`<option value="\${stopId}">\${station.name}</option>\`
        ).join('');
    }

    // Initialize location displays on page load
    window.addEventListener('DOMContentLoaded', () => {
      updateLocationDisplays();
      // Auto-load home station on page load
      useHomeLocation();

      // Setup address search input listener
      const searchInput = document.getElementById('addressSearch');
      searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          handleAddressSearch(e.target.value);
        }, 300);
      });

      // Close modal when clicking outside
      window.onclick = (event) => {
        const modal = document.getElementById('addressModal');
        if (event.target === modal) {
          closeAddressModal();
        }
      };
    });

    async function selectStation() {
      const stationSelect = document.getElementById('stationSelect');
      const stopId = stationSelect.value;

      if (!stopId) {
        alert('Please select a station');
        return;
      }

      const resultsDiv = document.getElementById('results');
      const resultsContent = document.getElementById('resultsContent');

      resultsDiv.style.display = 'block';
      resultsContent.innerHTML = '<div class="loading">🚇 Fetching train times...</div>';

      try {
        const response = await fetch(\`/api/station?stopId=\${stopId}\`);
        const data = await response.json();

        displayResults(data);
      } catch (error) {
        resultsContent.innerHTML = '<div class="error">Error fetching train data. Please try again.</div>';
      }
    }

    function displayResults(data) {
      const resultsContent = document.getElementById('resultsContent');

      // Extract terminal names from the first train in each direction
      let northTerminal = 'Northbound';
      let southTerminal = 'Southbound';

      if (data.arrivals.northbound && data.arrivals.northbound.length > 0) {
        // Extract terminal from direction string "to Terminal Name"
        const directionText = data.arrivals.northbound[0].direction;
        northTerminal = directionText.replace('to ', '');
      }

      if (data.arrivals.southbound && data.arrivals.southbound.length > 0) {
        const directionText = data.arrivals.southbound[0].direction;
        southTerminal = directionText.replace('to ', '');
      }

      let html = \`
        <div class="station-header">
          <h2>\${data.stationName}</h2>
          <p class="distance-info">Line: \${data.line}</p>
          \${data.distance ? \`<p class="distance-info">Distance: \${(data.distance * 5280).toFixed(0)} feet (\${data.distance.toFixed(2)} miles)</p>\` : ''}
        </div>
        <div class="directions">
      \`;

      // Northbound trains
      html += \`
        <div class="direction-card">
          <h3>⬆️ \${northTerminal}</h3>
      \`;

      if (data.arrivals.northbound && data.arrivals.northbound.length > 0) {
        data.arrivals.northbound.forEach(train => {
          html += \`
            <div class="train-arrival">
              <div>
                <span class="train-line-badge">\${train.line}</span>
                <span>\${train.direction}</span>
              </div>
              <div class="minutes">\${train.minutesAway} min</div>
            </div>
          \`;
        });
      } else {
        html += '<div class="no-trains">No upcoming trains</div>';
      }

      html += '</div>';

      // Southbound trains
      html += \`
        <div class="direction-card">
          <h3>⬇️ \${southTerminal}</h3>
      \`;

      if (data.arrivals.southbound && data.arrivals.southbound.length > 0) {
        data.arrivals.southbound.forEach(train => {
          html += \`
            <div class="train-arrival">
              <div>
                <span class="train-line-badge">\${train.line}</span>
                <span>\${train.direction}</span>
              </div>
              <div class="minutes">\${train.minutesAway} min</div>
            </div>
          \`;
        });
      } else {
        html += '<div class="no-trains">No upcoming trains</div>';
      }

      html += '</div></div>';

      html += \`
        <div style="text-align: center; margin-top: 20px; opacity: 0.7; font-size: 0.9em;">
          Last updated: \${new Date().toLocaleTimeString()}
        </div>
      \`;

      resultsContent.innerHTML = html;
    }

    function displayMultipleStations(data) {
      const resultsContent = document.getElementById('resultsContent');

      let html = '<div class="multiple-stations">';

      data.stations.forEach((station, index) => {
        // Extract terminal names from the first train in each direction
        let northTerminal = 'Northbound';
        let southTerminal = 'Southbound';

        if (station.arrivals.northbound && station.arrivals.northbound.length > 0) {
          const directionText = station.arrivals.northbound[0].direction;
          northTerminal = directionText.replace('to ', '');
        }

        if (station.arrivals.southbound && station.arrivals.southbound.length > 0) {
          const directionText = station.arrivals.southbound[0].direction;
          southTerminal = directionText.replace('to ', '');
        }

        html += \`
          <div class="station-section" style="margin-bottom: 30px; padding-bottom: 20px; border-bottom: 2px solid #e0e0e0;">
            <div class="station-header">
              <h2>\${station.stationName}</h2>
              <p class="distance-info">Line: \${station.line}</p>
              <p class="distance-info">Distance: \${(station.distance * 5280).toFixed(0)} feet (\${station.distance.toFixed(2)} miles)</p>
            </div>
            <div class="directions">
        \`;

        // Northbound trains
        html += \`
          <div class="direction-card">
            <h3>⬆️ \${northTerminal}</h3>
        \`;

        if (station.arrivals.northbound && station.arrivals.northbound.length > 0) {
          station.arrivals.northbound.forEach(train => {
            html += \`
              <div class="train-arrival">
                <div>
                  <span class="train-line-badge">\${train.line}</span>
                  <span>\${train.direction}</span>
                </div>
                <div class="minutes">\${train.minutesAway} min</div>
              </div>
            \`;
          });
        } else {
          html += '<div class="no-trains">No upcoming trains</div>';
        }

        html += '</div>';

        // Southbound trains
        html += \`
          <div class="direction-card">
            <h3>⬇️ \${southTerminal}</h3>
        \`;

        if (station.arrivals.southbound && station.arrivals.southbound.length > 0) {
          station.arrivals.southbound.forEach(train => {
            html += \`
              <div class="train-arrival">
                <div>
                  <span class="train-line-badge">\${train.line}</span>
                  <span>\${train.direction}</span>
                </div>
                <div class="minutes">\${train.minutesAway} min</div>
              </div>
            \`;
          });
        } else {
          html += '<div class="no-trains">No upcoming trains</div>';
        }

        html += '</div></div></div>';
      });

      html += \`
        <div style="text-align: center; margin-top: 20px; opacity: 0.7; font-size: 0.9em;">
          Last updated: \${new Date().toLocaleTimeString()}
        </div>
      \`;

      html += '</div>';
      resultsContent.innerHTML = html;
    }
  </script>
</body>
</html>
  `;
}

const server = http.createServer(async (req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;
  const query = parsedUrl.query;

  // CORS headers for API requests
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  if (pathname === '/') {
    const html = generateHTML();
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(html);
  }
  else if (pathname === '/api/nearest') {
    // Find nearest station and get arrivals
    const lat = parseFloat(query.lat);
    const lon = parseFloat(query.lon);

    if (isNaN(lat) || isNaN(lon)) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid coordinates' }));
      return;
    }

    const { stopId, station, distance } = findClosestStation(lat, lon);
    const arrivals = await getTrainArrivals(stopId);

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      stopId: stopId,
      stationName: station.name,
      line: station.line,
      distance: distance,
      arrivals: arrivals,
      timestamp: new Date().toISOString()
    }));
  }
  else if (pathname === '/api/nearby') {
    // Find multiple nearby stations (for work location)
    const lat = parseFloat(query.lat);
    const lon = parseFloat(query.lon);

    if (isNaN(lat) || isNaN(lon)) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid coordinates' }));
      return;
    }

    let nearbyStations = findNearbyStations(lat, lon);

    // If no stations within radius, find the nearest station
    if (nearbyStations.length === 0) {
      const { stopId, station, distance } = findClosestStation(lat, lon);
      nearbyStations = [{ stopId, station, distance }];
    }

    // Get arrivals for all nearby stations
    const stationsWithArrivals = await Promise.all(
      nearbyStations.map(async ({ stopId, station, distance }) => {
        const arrivals = await getTrainArrivals(stopId);
        return {
          stopId,
          stationName: station.name,
          line: station.line,
          distance,
          arrivals
        };
      })
    );

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      stations: stationsWithArrivals,
      timestamp: new Date().toISOString()
    }));
  }
  else if (pathname === '/api/station') {
    // Get arrivals for a specific station
    const stopId = query.stopId;

    if (!stopId || !STATIONS[stopId]) {
      res.writeHead(400, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'Invalid stop ID' }));
      return;
    }

    const station = STATIONS[stopId];
    const arrivals = await getTrainArrivals(stopId);

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      stopId: stopId,
      stationName: station.name,
      line: station.line,
      arrivals: arrivals,
      timestamp: new Date().toISOString()
    }));
  }
  else if (pathname === '/api/stations') {
    // Get list of all available stations
    const stationList = Object.entries(STATIONS).map(([stopId, station]) => ({
      stopId: stopId,
      name: station.name,
      line: station.line,
      lat: station.lat,
      lon: station.lon
    }));

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ stations: stationList }));
  }
  else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('Not Found');
  }
});

server.listen(PORT, () => {
  console.log(`\n🚇 MTA Train Tracker Web Server`);
  console.log(`================================`);
  console.log(`Server running at: http://localhost:${PORT}`);
  console.log(`\nAvailable endpoints:`);
  console.log(`  Main app:     http://localhost:${PORT}`);
  console.log(`  API nearest:  http://localhost:${PORT}/api/nearest?lat=LAT&lon=LON`);
  console.log(`  API station:  http://localhost:${PORT}/api/station?stopId=STOP_ID`);
  console.log(`  API stations: http://localhost:${PORT}/api/stations`);
  console.log(`\n${Object.keys(STATIONS).length} stations available`);
  console.log(`Monitoring all L and G train stations`);
});
