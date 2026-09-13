"""Live Garmin Connect fetch. Feeds the shared normalize/dedupe/store engine.
See .claude/specs/2026-09-12-garmin-fetch-design.md."""
from datetime import datetime, timezone

from .base import BaseFetcher
from .model import RawActivity


def gmt_to_dt(s: str) -> datetime:
    """'YYYY-MM-DD HH:MM:SS' (genuinely GMT) -> tz-aware UTC datetime."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def gmt_to_epoch(s: str) -> int:
    return int(gmt_to_dt(s).timestamp())


def extract_track(detail: dict) -> list[tuple[float, float]]:
    """geoPolylineDTO.polyline -> [(lat, lon)]; [] when absent."""
    pts = ((detail or {}).get("geoPolylineDTO") or {}).get("polyline") or []
    return [(p["lat"], p["lon"]) for p in pts]


def filter_after(items: list[dict], after_epoch: int) -> list[dict]:
    """Keep list items strictly after the high-water epoch."""
    return [i for i in items if gmt_to_epoch(i["startTimeGMT"]) > after_epoch]


def list_item_to_raw(item: dict, track: list[tuple[float, float]]) -> RawActivity:
    return RawActivity(
        source="garmin",
        source_id=str(item["activityId"]),
        name=item.get("activityName") or "",
        type_raw=item["activityType"]["typeKey"],
        start_time=gmt_to_dt(item["startTimeGMT"]),
        distance_m=float(item.get("distance") or 0),
        moving_time_s=int(item.get("movingDuration") or item.get("duration") or 0),
        elevation_gain_m=float(item.get("elevationGain") or 0),
        track=track,
        source_file="garmin-api",
    )


class GarminFetcher(BaseFetcher):
    source = "garmin"

    def activities(self):
        raise NotImplementedError("filled in Task 2")


def main():
    raise SystemExit("garmin_fetch not yet implemented")


if __name__ == "__main__":
    main()
