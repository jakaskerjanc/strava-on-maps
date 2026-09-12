from . import store
from .model import Activity


def _merge(base: Activity, incoming: Activity, winner: str) -> Activity:
    """Keep base.id (canonical, stable). Fill both native ids. Apply policy."""
    strava_id = base.strava_id or incoming.strava_id
    garmin_id = base.garmin_id or incoming.garmin_id
    win_id_attr = "strava_id" if winner == "strava" else "garmin_id"
    if getattr(incoming, win_id_attr):
        meta = incoming
    elif getattr(base, win_id_attr):
        meta = base
    else:
        meta = incoming   # winner's source not present on either -> fresh incoming wins
    geo = incoming if len(incoming.polyline) > len(base.polyline) else base
    return Activity(
        id=base.id, strava_id=strava_id, garmin_id=garmin_id,
        name=meta.name, type=meta.type, start_time=meta.start_time,
        distance=meta.distance, moving_time=meta.moving_time,
        elevation_gain=meta.elevation_gain,
        polyline=geo.polyline, start_lat=geo.start_lat, start_lng=geo.start_lng,
    )


def reconcile(conn, incoming: Activity, *, window_s=90, moving_pct=0.05,
              name_stats_winner="strava") -> str:
    service = "strava" if incoming.strava_id else "garmin"
    sid = incoming.strava_id or incoming.garmin_id

    # 1. exact id-column match -> update in place
    existing = store.find_by_service_id(conn, service, sid)
    if existing:
        store.upsert(conn, _merge(existing, incoming, name_stats_winner))
        return "update"

    # 2. cross-source time + moving_time match
    for cand in store.find_near(conn, incoming.start_time, window_s):
        a, b = cand.moving_time, incoming.moving_time
        close = (a and b and abs(a - b) <= moving_pct * max(a, b)) or (not a and not b)
        if close:
            store.upsert(conn, _merge(cand, incoming, name_stats_winner))
            return "merge"

    # 3. new
    store.upsert(conn, incoming)
    return "insert"
