from ingest import store, dedupe
from ingest.model import Activity


def _a(**kw):
    base = dict(id="s:1", strava_id="1", garmin_id=None, name="Strava Name", type="Ride",
                start_time="2026-08-01T06:30:00+00:00", distance=100.0, moving_time=1000,
                elevation_gain=5.0, polyline="aaaa", start_lat=46.0, start_lng=14.0)
    base.update(kw)
    return Activity(**base)


def _fresh():
    conn = store.connect(":memory:"); store.init_schema(conn)
    return conn


def test_new_insert():
    conn = _fresh()
    assert dedupe.reconcile(conn, _a()) == "insert"
    assert len(store.all_activities(conn)) == 1


def test_exact_id_updates():
    conn = _fresh()
    dedupe.reconcile(conn, _a(name="old"))
    assert dedupe.reconcile(conn, _a(name="new")) == "update"
    assert store.find_by_service_id(conn, "strava", "1").name == "new"


def test_cross_source_merge_fills_other_id_keeps_canonical():
    conn = _fresh()
    dedupe.reconcile(conn, _a())                                  # strava first
    garmin = Activity(id="g:900", strava_id=None, garmin_id="900", name="Garmin Name",
                      type="Ride", start_time="2026-08-01T06:30:30+00:00",  # 30s off
                      distance=101.0, moving_time=1010, elevation_gain=5.0,
                      polyline="bbbbbbbb", start_lat=46.0, start_lng=14.0)   # denser geometry
    assert dedupe.reconcile(conn, garmin) == "merge"
    rows = store.all_activities(conn)
    assert len(rows) == 1
    m = rows[0]
    assert m.id == "s:1"                       # canonical id unchanged
    assert m.strava_id == "1" and m.garmin_id == "900"
    assert m.name == "Strava Name"             # name/stats: strava wins
    assert m.polyline == "bbbbbbbb"            # geometry: more points wins


def test_cross_source_no_match_when_time_far():
    conn = _fresh()
    dedupe.reconcile(conn, _a())
    other = _a(id="g:900", strava_id=None, garmin_id="900",
               start_time="2026-08-01T09:00:00+00:00")
    assert dedupe.reconcile(conn, other) == "insert"
    assert len(store.all_activities(conn)) == 2


def test_garmin_only_exact_update_refreshes_metadata():
    conn = _fresh()
    garmin = Activity(id="g:900", strava_id=None, garmin_id="900", name="Garmin Name",
                      type="Ride", start_time="2026-08-01T06:30:00+00:00",
                      distance=100.0, moving_time=1000, elevation_gain=5.0,
                      polyline="cccc", start_lat=46.0, start_lng=14.0)
    dedupe.reconcile(conn, garmin)
    updated = Activity(id="g:900", strava_id=None, garmin_id="900", name="Garmin Name v2",
                       type="Ride", start_time="2026-08-01T06:30:00+00:00",
                       distance=150.0, moving_time=1500, elevation_gain=5.0,
                       polyline="cccc", start_lat=46.0, start_lng=14.0)
    assert dedupe.reconcile(conn, updated) == "update"
    rows = store.all_activities(conn)
    assert len(rows) == 1
    m = rows[0]
    assert m.name == "Garmin Name v2"
    assert m.distance == 150.0
    assert m.moving_time == 1500


def test_idempotent_reruns():
    conn = _fresh()
    dedupe.reconcile(conn, _a())
    dedupe.reconcile(conn, _a())
    dedupe.reconcile(conn, _a())
    assert len(store.all_activities(conn)) == 1
