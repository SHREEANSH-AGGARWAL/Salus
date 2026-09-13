/* ═══════════════════════════════════════════════════════════════════════════
   SALUS — Delhi geography reference data
   ───────────────────────────────────────────────────────────────────────────
   Everything the radar map needs to look like Delhi: the NCT outline, the
   Yamuna, the two ring roads, landmarks, district labels, and a list of
   well-known locations used to pre-fill coordinates in the forms.

   All coordinates are [latitude, longitude] and are deliberately simplified —
   this is a tactical schematic, not a survey map.
   ═══════════════════════════════════════════════════════════════════════════ */

'use strict';

const DELHI = {

  // Geographic centre of the operating area (India Gate / Rajpath area).
  CENTER: { lat: 28.6139, lng: 77.2090 },

  // National Capital Territory administrative outline.
  BOUNDARY: [
    [28.875, 77.155], [28.855, 77.200], [28.830, 77.245], [28.800, 77.268],
    [28.755, 77.288], [28.730, 77.320], [28.700, 77.345], [28.660, 77.338],
    [28.625, 77.330], [28.590, 77.330], [28.555, 77.325], [28.510, 77.310],
    [28.480, 77.295], [28.440, 77.275], [28.410, 77.225], [28.405, 77.160],
    [28.420, 77.100], [28.455, 77.035], [28.500, 76.975], [28.545, 76.905],
    [28.590, 76.850], [28.640, 76.845], [28.690, 76.870], [28.735, 76.910],
    [28.780, 76.965], [28.820, 77.030], [28.850, 77.095],
  ],

  // The Yamuna, north to south.
  YAMUNA: [
    [28.860, 77.215], [28.820, 77.222], [28.780, 77.228], [28.745, 77.232],
    [28.712, 77.228], [28.690, 77.233], [28.668, 77.241], [28.652, 77.247],
    [28.635, 77.252], [28.622, 77.252], [28.605, 77.258], [28.590, 77.264],
    [28.572, 77.278], [28.556, 77.296], [28.535, 77.312], [28.505, 77.320],
    [28.470, 77.312], [28.440, 77.300], [28.412, 77.288],
  ],

  // Inner Ring Road.
  RING_ROAD: [
    [28.5735, 77.2590], [28.5670, 77.2460], [28.5678, 77.2085], [28.5760, 77.1880],
    [28.5905, 77.1620], [28.6120, 77.1450], [28.6330, 77.1290], [28.6520, 77.1290],
    [28.6720, 77.1470], [28.6880, 77.1670], [28.7070, 77.1780], [28.7060, 77.2000],
    [28.6960, 77.2170], [28.6810, 77.2270], [28.6670, 77.2290], [28.6560, 77.2420],
    [28.6400, 77.2500], [28.6200, 77.2540], [28.6000, 77.2570], [28.5860, 77.2590],
  ],

  // Outer Ring Road.
  OUTER_RING: [
    [28.5490, 77.2830], [28.5430, 77.2520], [28.5320, 77.2180], [28.5330, 77.1740],
    [28.5560, 77.1350], [28.5860, 77.1100], [28.6180, 77.0850], [28.6560, 77.0770],
    [28.6930, 77.0880], [28.7250, 77.1140], [28.7400, 77.1540], [28.7330, 77.1950],
    [28.7220, 77.2320], [28.7010, 77.2740], [28.6720, 77.2960], [28.6400, 77.3120],
    [28.6100, 77.3160], [28.5820, 77.3080], [28.5610, 77.2980],
  ],

  // Reference points. `kind` drives the glyph and colour on the radar.
  //   hub       — airports, rail terminals, bus terminals
  //   hospital  — major trauma centres
  //   landmark  — recognisable monuments / civic buildings
  //   locality  — neighbourhood anchors for orientation
  //   ncr       — satellite cities outside the NCT
  LANDMARKS: [
    { name: 'IGI Airport T3',      lat: 28.5562, lng: 77.0999, kind: 'hub' },
    { name: 'New Delhi Rly',       lat: 28.6420, lng: 77.2190, kind: 'hub' },
    { name: 'Kashmere Gate ISBT',  lat: 28.6675, lng: 77.2286, kind: 'hub' },
    { name: 'Nizamuddin Rly',      lat: 28.5883, lng: 77.2510, kind: 'hub' },
    { name: 'Anand Vihar ISBT',    lat: 28.6469, lng: 77.3155, kind: 'hub' },
    { name: 'Palam AFS',           lat: 28.5665, lng: 77.0870, kind: 'hub' },

    { name: 'AIIMS Trauma',        lat: 28.5672, lng: 77.2100, kind: 'hospital' },
    { name: 'Safdarjung Hosp',     lat: 28.5685, lng: 77.2055, kind: 'hospital' },
    { name: 'LNJP Hospital',       lat: 28.6395, lng: 77.2400, kind: 'hospital' },
    { name: 'RML Hospital',        lat: 28.6250, lng: 77.2010, kind: 'hospital' },
    { name: 'GTB Hospital',        lat: 28.6840, lng: 77.3120, kind: 'hospital' },
    { name: 'Max Saket',           lat: 28.5280, lng: 77.2160, kind: 'hospital' },

    { name: 'Red Fort',            lat: 28.6562, lng: 77.2410, kind: 'landmark' },
    { name: 'Jama Masjid',         lat: 28.6507, lng: 77.2334, kind: 'landmark' },
    { name: 'India Gate',          lat: 28.6129, lng: 77.2295, kind: 'landmark' },
    { name: 'Connaught Place',     lat: 28.6315, lng: 77.2167, kind: 'landmark' },
    { name: 'Rashtrapati Bhavan',  lat: 28.6143, lng: 77.1994, kind: 'landmark' },
    { name: "Humayun's Tomb",      lat: 28.5933, lng: 77.2507, kind: 'landmark' },
    { name: 'Lotus Temple',        lat: 28.5535, lng: 77.2588, kind: 'landmark' },
    { name: 'Akshardham',          lat: 28.6127, lng: 77.2773, kind: 'landmark' },
    { name: 'Qutub Minar',         lat: 28.5245, lng: 77.1855, kind: 'landmark' },

    { name: 'Rohini',              lat: 28.7360, lng: 77.1100, kind: 'locality' },
    { name: 'Pitampura',           lat: 28.6990, lng: 77.1310, kind: 'locality' },
    { name: 'Narela',              lat: 28.8553, lng: 77.0920, kind: 'locality' },
    { name: 'Dwarka',              lat: 28.5921, lng: 77.0460, kind: 'locality' },
    { name: 'Najafgarh',           lat: 28.6090, lng: 76.9800, kind: 'locality' },
    { name: 'Karol Bagh',          lat: 28.6519, lng: 77.1909, kind: 'locality' },
    { name: 'Mayapuri',            lat: 28.6380, lng: 77.1320, kind: 'locality' },
    { name: 'Lajpat Nagar',        lat: 28.5680, lng: 77.2430, kind: 'locality' },
    { name: 'Nehru Place',         lat: 28.5494, lng: 77.2501, kind: 'locality' },
    { name: 'Okhla Industrial',    lat: 28.5350, lng: 77.2730, kind: 'locality' },
    { name: 'Preet Vihar',         lat: 28.6410, lng: 77.2940, kind: 'locality' },
    { name: 'Vasant Kunj',         lat: 28.5200, lng: 77.1590, kind: 'locality' },

    { name: 'Noida',               lat: 28.5355, lng: 77.3910, kind: 'ncr' },
    { name: 'Ghaziabad',           lat: 28.6692, lng: 77.4538, kind: 'ncr' },
    { name: 'Gurugram',            lat: 28.4595, lng: 77.0266, kind: 'ncr' },
    { name: 'Faridabad',           lat: 28.4089, lng: 77.3178, kind: 'ncr' },
  ],

  // Revenue district labels, drawn very dim for orientation only.
  DISTRICTS: [
    { name: 'NORTH WEST', lat: 28.7300, lng: 77.0750 },
    { name: 'NORTH',      lat: 28.7750, lng: 77.1850 },
    { name: 'NORTH EAST', lat: 28.6950, lng: 77.2820 },
    { name: 'WEST',       lat: 28.6450, lng: 77.0750 },
    { name: 'CENTRAL',    lat: 28.6620, lng: 77.2080 },
    { name: 'SHAHDARA',   lat: 28.6720, lng: 77.3050 },
    { name: 'EAST',       lat: 28.6150, lng: 77.2960 },
    { name: 'NEW DELHI',  lat: 28.6000, lng: 77.1950 },
    { name: 'SOUTH WEST', lat: 28.5450, lng: 77.0600 },
    { name: 'SOUTH',      lat: 28.4900, lng: 77.1900 },
    { name: 'SOUTH EAST', lat: 28.5350, lng: 77.2750 },
  ],

  // Quick-pick coordinates offered in the "register" forms so nobody has to
  // hunt for a latitude.
  PRESETS: [
    { label: 'Connaught Place / Rajiv Chowk',   lat: 28.6315, lng: 77.2167 },
    { label: 'Chandni Chowk / Old Delhi',        lat: 28.6562, lng: 77.2301 },
    { label: 'Yamuna Floodplain (Kashmere Gt)',  lat: 28.6650, lng: 77.2380 },
    { label: 'India Gate / Central Vista',       lat: 28.6129, lng: 77.2295 },
    { label: 'Karol Bagh',                       lat: 28.6519, lng: 77.1909 },
    { label: 'Mayapuri Industrial Area',         lat: 28.6380, lng: 77.1320 },
    { label: 'Lajpat Nagar',                     lat: 28.5680, lng: 77.2430 },
    { label: 'AIIMS / Safdarjung',               lat: 28.5672, lng: 77.2100 },
    { label: 'Okhla Industrial Area',            lat: 28.5350, lng: 77.2730 },
    { label: 'Saket / Malviya Nagar',            lat: 28.5245, lng: 77.2066 },
    { label: 'Dwarka Sector 21',                 lat: 28.5525, lng: 77.0587 },
    { label: 'IGI Airport',                      lat: 28.5562, lng: 77.0999 },
    { label: 'Rohini Sector 18',                 lat: 28.7360, lng: 77.1100 },
    { label: 'Narela Industrial',                lat: 28.8553, lng: 77.0920 },
    { label: 'Shahdara / Seelampur',             lat: 28.6700, lng: 77.2900 },
    { label: 'Najafgarh',                        lat: 28.6090, lng: 76.9800 },
  ],
};

// Distance in km between two [lat,lng] points (haversine).
function kmBetween(lat1, lng1, lat2, lng2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLng = (lng2 - lng1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
}

// Compass bearing from point 1 to point 2, in degrees from north.
function bearingBetween(lat1, lng1, lat2, lng2) {
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180;
  const Δλ = (lng2 - lng1) * Math.PI / 180;
  const y = Math.sin(Δλ) * Math.cos(φ2);
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

const COMPASS_POINTS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                        'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

function compassLabel(deg) {
  return COMPASS_POINTS[Math.round(deg / 22.5) % 16];
}

// Nearest named reference point to a coordinate — turns raw lat/lng into
// something a human can picture.
function nearestLandmark(lat, lng) {
  let best = null, bestKm = Infinity;
  for (const lm of DELHI.LANDMARKS) {
    const d = kmBetween(lat, lng, lm.lat, lm.lng);
    if (d < bestKm) { bestKm = d; best = lm; }
  }
  return best ? { landmark: best, km: bestKm } : null;
}

// "2.4 km NE of India Gate"
function describeLocation(lat, lng) {
  const near = nearestLandmark(lat, lng);
  if (!near) return `${lat.toFixed(3)}°N ${lng.toFixed(3)}°E`;
  if (near.km < 0.4) return `at ${near.landmark.name}`;
  const bearing = compassLabel(bearingBetween(near.landmark.lat, near.landmark.lng, lat, lng));
  return `${near.km.toFixed(1)} km ${bearing} of ${near.landmark.name}`;
}
