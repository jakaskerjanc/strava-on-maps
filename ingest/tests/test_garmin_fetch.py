import json
import os
from datetime import datetime, timezone

from ingest import garmin_fetch as gf
from ingest.model import RawActivity

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _list():
    with open(os.path.join(FIX, "garmin_api_list.json")) as f:
        return json.load(f)


def _detail():
    with open(os.path.join(FIX, "garmin_api_detail.json")) as f:
        return json.load(f)


def test_gmt_to_dt_is_utc():
    dt = gf.gmt_to_dt("2026-09-12 06:30:00")
    assert dt == datetime(2026, 9, 12, 6, 30, 0, tzinfo=timezone.utc)
    assert gf.gmt_to_epoch("2026-09-12 06:30:00") == int(dt.timestamp())


def test_extract_track_maps_lat_lon():
    assert gf.extract_track(_detail())[0] == (46.05, 14.5)
    assert len(gf.extract_track(_detail())) == 4
    assert gf.extract_track({}) == []
    assert gf.extract_track({"geoPolylineDTO": {}}) == []


def test_filter_after_is_strictly_after():
    items = _list()
    boundary = gf.gmt_to_epoch("2026-09-12 06:30:00")  # exact start of item 0
    kept = gf.filter_after(items, boundary)
    assert [i["activityId"] for i in kept] == []       # strict >: equal is excluded
    kept = gf.filter_after(items, boundary - 1)
    assert [i["activityId"] for i in kept] == [5000001]


def test_list_item_to_raw_no_unit_scaling():
    outdoor, indoor = _list()
    r = gf.list_item_to_raw(outdoor, [(46.05, 14.5)])
    assert isinstance(r, RawActivity)
    assert r.source == "garmin" and r.source_id == "5000001"
    assert r.type_raw == "running" and r.name == "Morning Run"
    assert r.distance_m == 10006.79 and r.elevation_gain_m == 34.0
    assert r.moving_time_s == 3200          # movingDuration, seconds, no /1000
    assert r.start_time == datetime(2026, 9, 12, 6, 30, tzinfo=timezone.utc)
    assert r.track == [(46.05, 14.5)] and r.source_file == "garmin-api"


def test_list_item_to_raw_moving_duration_fallback_and_empty_track():
    _, indoor = _list()
    r = gf.list_item_to_raw(indoor, [])
    assert r.moving_time_s == 2400          # movingDuration null -> duration
    assert r.track == [] and r.name == "Gym"
