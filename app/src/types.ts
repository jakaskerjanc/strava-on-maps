// Frontend copy of the GeoJSON data contract produced by the pipeline.
// Keep in sync with scripts/types.ts (ActivityFeatureProps).

/** UI color scheme. Drives both the panel chrome and the Mapbox base style. */
export type Theme = "light" | "dark";

export interface ActivityFeatureProps {
  /** namespaced wire id ("s:<stravaId>" / "g:<garminId>") */
  id: string;
  name: string;
  /** activity-type filter key (Strava sport_type) */
  type: string;
  /** epoch seconds — used for numeric date-range filtering */
  ts: number;
  start_date: string;
  /** meters */
  distance: number;
  /** seconds */
  moving_time: number;
  /** meters */
  elevation_gain: number;
}

export type ActivityFeature = GeoJSON.Feature<
  GeoJSON.LineString,
  ActivityFeatureProps
>;

export type ActivityFeatureCollection = GeoJSON.FeatureCollection<
  GeoJSON.LineString,
  ActivityFeatureProps
>;

/**
 * Compact wire format fetched from app/public/tracks.json and decoded in the
 * browser (see tracks.ts). Each track is the filterable props plus a
 * Google-encoded polyline of the route — ~2x smaller than decoded GeoJSON
 * coordinate arrays. Keep in sync with scripts/types.ts (the encoder side).
 */
export interface EncodedTrack extends ActivityFeatureProps {
  /** Google-encoded polyline of the route, [lat,lng] precision-5. */
  poly: string;
}

/** Root shape of app/public/tracks.json. */
export interface TrackPayload {
  /** Wire-format version, bumped on breaking shape changes. */
  v: number;
  tracks: EncodedTrack[];
}

// --- City distance comparisons ---------------------------------------------
// Frontend copy of the city-distances.json wire format.
// Keep in sync with scripts/city-types.ts (the encoder side).

/** Comparison group; also the per-city route key in city-distances.json. */
export type Profile = "cycling" | "walking";

export interface EncodedCityRoute {
  /** OSRM route distance, meters */
  m: number;
  /** Google-encoded polyline of the route, [lat,lng] precision-5. */
  poly: string;
}

export interface EncodedCity {
  /** GeoNames geonameid */
  id: number;
  name: string;
  /** ISO 3166-1 alpha-2 */
  country: string;
  /** GeoNames feature code: PPLC national capital, PPLA regional capital, PPL… */
  fc: string;
  lat: number;
  lon: number;
  population: number;
  cycling: EncodedCityRoute | null;
  walking: EncodedCityRoute | null;
}

/** Root shape of app/public/city-distances.json. */
export interface CityDistancePayload {
  /** Wire-format version, bumped on breaking shape changes. */
  v: number;
  generated: string;
  router: string;
  simplifyM: number;
  origin: { name: string; lat: number; lon: number };
  cities: EncodedCity[];
}
