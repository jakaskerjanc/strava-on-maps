# Design: Export/fetch ingestion → SQLite store

Date: 2026-09-11
Status: draft, pending review

**Supersedes** the ingest and storage sections of
`2026-08-27-garmin-ingest-design.md` / `-plan.md` (live-only Garmin API model).
It **reuses** those docs' frontend refactors: `source` field, collapsed single
`polyline`, namespaced wire ids (`s:` / `g:`), `activityLink`, payload `v` → 2.

## Problem

Strava can no longer be polled and the Garmin live API is fragile. We have full
bulk exports from both services. Replace the single-source live-poll intake with
a generic ingestion architecture that:

- Consolidates all activities from bulk exports (one-shot backfill) into one
  store, normalized and de-duplicated.
- Keeps the door open to append new activities later via live fetch (Garmin
  first, Strava possibly), through the *same* pipeline.
- Keeps the existing build → `tracks.json` → React/Mapbox → Pages deploy intact.

## Data reality (verified against the real exports, 2026-09-11)

| | Strava export | Garmin export |
|---|---|---|
| Activities | **490** (2023-10 → 2026-09) | **353** (2025-04 → 2026-09) |
| Per-activity geometry | keyed by id via `activities.csv` → 352 `.fit.gz`, 121 `.tcx.gz`, 15 `.gpx` | in `UploadedFiles_*.zip`: 7,721 FIT named by *upload-file id* |
| Stats/type | `activities.csv` (103 cols) | `*_summarizedActivities.json` (scaled units) |
| Overlap (±3 min) | — | Garmin-only: **1**, Strava-only: **138** (all pre-watch) |

Verified facts that shape the design:

- **Formats are FIT + TCX + GPX** (TCX is significant — 121 files), not just
  FIT/GPX.
- Garmin `summarizedActivities.json` has stats/type/`activityId`/bounding-box
  but **no route geometry**. Units are scaled: timestamps in **ms**, distance &
  elevation **×100** (cm / cm), duration in **ms**. `activityType` is a lower-
  snake key (`running`, `cycling`, `strength_training`, `tennis_v2`,
  `paddelball`, `skating_ws`, `bouldering`, `track_running`, …).
- The Garmin FIT haystack is **filterable**: each FIT's `file_id` message has a
  `type` field; `type == 'activity'` isolates ~353 real activities out of 7,721
  (rest are `monitoring_b` etc.). Confirmed outdoor activity FITs carry full GPS
  (`record.position_lat/long`, thousands of points); indoor ones have 0.
  Positions are FIT **semicircles** → degrees = `value * 180 / 2**31`.
- Strava stores the original device FIT per activity (Strava id → `Filename`),
  so its geometry equals Garmin's for the overlap.

## Architecture

Four **independently runnable** components. Two importers extend one importer
base; two fetchers extend one fetcher base; both bases share the ingest engine
(normalize → dedupe → store). Every component reconciles against the store, so
each is idempotent and cross-source-aware regardless of run order.

```
strava_import.py  (StravaImporter) ─┐  extends BaseImporter ┐
garmin_import.py  (GarminImporter) ─┘  (local export files) │
                                                            ├─ Ingestor.run():
garmin_fetch.py   (GarminFetcher)  ─┐  extends BaseFetcher  │   for raw in activities():
strava_fetch.py   (StravaFetcher)  ─┘  (remote API)         ┘     normalize → dedupe → store
                                                                        │
                            data/activities.sqlite  (committed, source of truth)
                                                                        │
                            build-tracks.ts (reads SQLite) → app/public/tracks.json
                                                                        │
                                              React + Mapbox app → Pages
```

### Class hierarchy (`ingest/`)

- `ingest/base.py`
  - `Ingestor` — abstract engine. `run()` loads the store, iterates
    `activities()`, and for each: `normalize` → `dedupe.reconcile(incoming,
    store)` → `store.upsert`. Owns all shared wiring. Abstract:
    `activities() -> Iterable[RawActivity]`, `source: str`.
  - `BaseImporter(Ingestor)` — local bulk exports. Shared helpers: locate export
    root (CLI arg / env), dispatch a per-activity file to the right format parser
    (`parse/{fit,tcx,gpx}.py`), gunzip transparently.
  - `BaseFetcher(Ingestor)` — remote API. Shared helpers: token load/rotate,
    incremental "after high-water mark from the store" windowing, 1 req/s
    throttle, fail-loud on auth rejection.
- Components (each an entry point + subclass implementing `activities()`):
  - `strava_import.py` → `StravaImporter` — enumerate `activities.csv`; for each
    row yield a `RawActivity` (stats from CSV, geometry from the referenced
    file).
  - `garmin_import.py` → `GarminImporter` — load `*_summarizedActivities.json`;
    index activity FITs (`file_id.type == 'activity'`) from `UploadedFiles_*.zip`
    by `session.start_time`; yield `RawActivity` (stats/type/id from summary,
    geometry from matched FIT).
  - `garmin_fetch.py` → `GarminFetcher` — Garmin Connect API list + details
    (reuses the 2026-08-27 plan's Python shim: auth, token rotation, detail
    throttle). Later phase.
  - `strava_fetch.py` → `StravaFetcher` — Strava API (stub/deferred; only if
    re-enabled). Later phase.

### Entry points (npm scripts)

```
import:strava  → python ingest/strava_import.py  <export-root>
import:garmin  → python ingest/garmin_import.py  <export-root>
fetch:garmin   → python ingest/garmin_fetch.py   (later)
fetch:strava   → python ingest/strava_fetch.py   (later)
```

Bulk backfill = run `import:strava` then `import:garmin` once; commit the DB.
Steady state (later) = a scheduled `fetch:garmin` appends + commits.

## `RawActivity` (source-agnostic intermediate, `ingest/model.py`)

```
source:          "strava" | "garmin"
source_id:       str            # native id (Strava activity id / Garmin activityId)
name:            str
type_raw:        str            # source's own type key, before normalization
start_time:      datetime (UTC, tz-aware)
distance_m:      float
moving_time_s:   int
elevation_gain_m:float
track:           list[(lat, lon)]  # decoded degrees; [] when no GPS
source_file:     str | None     # provenance (filename / zip entry / "api")
```

## Normalize (`ingest/normalize.py`)

- **Type map** onto the canonical vocabulary (`Run`, `Ride`, `Hike`, `Walk`,
  `WeightTraining`, `Swim`, `RockClimbing`, `Rowing`, `StairStepper`,
  `Badminton`, `Volleyball`, `IceSkate`, `Workout`, …). Covers Strava types and
  Garmin snake keys (incl. the new ones seen in the export: `tennis_v2`,
  `paddelball`, `skating_ws`, `bouldering`, `track_running`, `indoor_*`).
  Unmapped key → title-cased + warned (never silently bucketed).
- **Units**: Strava CSV already SI-ish; Garmin summary needs ms→s, ×100→m.
  Emit meters / seconds / ISO-8601-UTC.
- **Geometry**: FIT semicircles → degrees; encode `track` as a **precision-5
  Google polyline** (full resolution; `build-tracks` simplifies at build). `[]`
  track → `""` (no GPS).

## Dedupe & merge (`ingest/dedupe.py`) — per component, idempotent

`reconcile(incoming: RawActivity, store)` for every component run:

1. **Exact**: `(source, source_id)` already stored → update that row in place.
2. **Cross-source**: else find a stored activity whose `start_time` is within
   **±90 s** *and* `moving_time` within **±5 %** → same real activity from
   another source. Merge per policy; record the new source in `activity_sources`.
   Do **not** change the canonical `id` (keeps `tracks.json` links stable).
3. **New**: else insert; assign canonical `id`.

**Merge policy** (configurable per field; default for this dataset):

- **name, stats** → **Strava wins** (your curated names / edits).
- **geometry** → the track with more points wins (equal underlying FIT → no-op).
- **Garmin `activityId`** → always retained in `activity_sources` so a later
  `garmin_fetch` matches by exact id and never re-inserts.

Canonical `id` assignment: prefer a Strava id when the activity has one
(`s:<stravaId>`), else `g:<garminId>` — applied deterministically so re-runs
converge no matter which component ran first.

## SQLite schema (`data/activities.sqlite`, committed)

`activities` (one row per canonical activity):

| col | type | note |
|---|---|---|
| `id` | TEXT PK | `s:<id>` / `g:<id>` (canonical, stable) |
| `source` | TEXT | canonical source per policy |
| `name` | TEXT | |
| `type` | TEXT | canonical vocabulary |
| `start_time` | TEXT | ISO-8601 UTC |
| `distance` | REAL | meters |
| `moving_time` | INTEGER | seconds |
| `elevation_gain` | REAL | meters |
| `polyline` | TEXT | full-res Google polyline; `''` = no GPS |
| `start_lat`, `start_lng` | REAL | dedup + future clustering |

`activity_sources` (all raw contributors — auditable dedup + dual deep-links):

| col | type |
|---|---|
| `activity_id` | TEXT FK → activities.id |
| `source` | TEXT |
| `source_id` | TEXT |
| `source_file` | TEXT |

Access from Python: stdlib `sqlite3`. Access from the TS build:
**better-sqlite3** (reliable on CI Node 22; `node:sqlite` is still flagged
there).

## TS build + frontend

- `build-tracks.ts` reads SQLite (better-sqlite3) instead of
  `data/activities.json`: `SELECT` activities with a non-empty `polyline`,
  decode → `simplify.ts` → re-encode → `EncodedTrack[]`. `tracks.json` shape
  unchanged except namespaced string `id` + payload `v` → 2.
- Frontend: adopt the 2026-08-27 plan's Task 4 changes only — string `id`,
  `activityLink(id)` returning a Strava **or** Garmin URL (from
  `activity_sources`). No new UI.

## Migration & retirement

- After the first backfill, gate on parity vs the current build: assert
  `tracks.json` still has ≥ the current routed count and that existing Strava
  ids are all present, before deleting `data/activities.json`.
- Remove the live-poll files: `scripts/strava.ts`, `scripts/get-refresh-token.ts`,
  `scripts/sync.ts` (superseded by the fetcher components).
- `data/activities.json` retired from the pipeline (kept in git history).

## Testing

- **Python (pytest, new)** — small redacted fixtures: one FIT (outdoor + one
  indoor), one TCX, one GPX, a trimmed `activities.csv`, a trimmed
  `summarizedActivities.json`, a tiny zip with 2–3 activity FITs + 1 monitoring
  FIT.
  - parsers: FIT/TCX/GPX → track + summary; semicircle conversion.
  - `garmin_import`: `file_id.type` filter picks only activities; summary↔FIT
    match by start_time.
  - normalize: type map (incl. unmapped-warn), unit scaling.
  - dedupe: exact `source_id` update; cross-source ±90 s / ±5 % match; new
    insert; **idempotent re-run** (running a component twice changes nothing).
  - store: upsert + `activity_sources` rows.
- **TS (`node:test`)** — fixture SQLite DB → `build-tracks` → assert
  `tracks.json` shape/version; existing `simplify` tests stay.
- **App (vitest)** — unchanged apart from id/link fixtures (per 2026-08-27 Task
  4).

## CI / workflow

Raw exports are **not committed** (gitignored `data/raw/`), so CI cannot rebuild
the DB from scratch. CI stays build-only: on push, `build-tracks` (committed DB →
`tracks.json`) → Pages. The daily cron was already removed (`ae51604`). When
`fetch:garmin` lands, a scheduled job runs it, commits the updated DB, and the
push triggers the existing build+deploy.

## Dependencies

- Python (`requirements.txt`): `fitdecode`, `gpxpy`, a TCX parser
  (`python-tcxparser` or stdlib `xml.etree`), plus (later, fetch) the 2026-08-27
  pins `garminconnect` + `curl_cffi`. `sqlite3` is stdlib.
- Node: add `better-sqlite3` to the pipeline workspace.

## Non-goals / open items

- Garmin FIT haystack is used **only** for the ~353 activity-type files; daily
  monitoring FITs are ignored.
- `strava_fetch` is a deferred stub (Strava polling is dead today); the class
  exists so the fetcher base has a second implementation slot.
- Exact TCX field paths and the `python-tcxparser` vs stdlib choice are settled
  during implementation against the fixtures (low risk; standard schema).

## File plan

Add: `requirements.txt`, `ingest/__init__.py`, `ingest/model.py`,
`ingest/base.py`, `ingest/normalize.py`, `ingest/dedupe.py`, `ingest/store.py`,
`ingest/parse/{fit,tcx,gpx}.py`, `ingest/strava_import.py`,
`ingest/garmin_import.py`, `ingest/garmin_fetch.py`, `ingest/strava_fetch.py`,
`ingest/**/*_test.py` (pytest), `data/activities.sqlite`.

Edit: `scripts/build-tracks.ts`, `scripts/types.ts`, `app/src/*` (Task 4 subset),
`package.json` (scripts + `better-sqlite3`), `.gitignore` (`data/raw/`, `.venv/`),
`.github/workflows/deploy.yml`, `README.md`.

Delete: `scripts/strava.ts`, `scripts/get-refresh-token.ts`, `scripts/sync.ts`,
`data/activities.json` (after parity gate).
