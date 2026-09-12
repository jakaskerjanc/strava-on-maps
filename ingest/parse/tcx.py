import xml.etree.ElementTree as ET
from datetime import datetime
from . import ParsedTrack

_NS = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}


def parse_tcx(fileobj) -> ParsedTrack:
    root = ET.parse(fileobj).getroot()
    pts, start = [], None
    for tp in root.iterfind(".//t:Trackpoint", _NS):
        pos = tp.find("t:Position", _NS)
        if pos is None:
            continue
        lat = pos.find("t:LatitudeDegrees", _NS)
        lon = pos.find("t:LongitudeDegrees", _NS)
        if lat is None or lon is None or not lat.text or not lon.text:
            continue
        pts.append((float(lat.text), float(lon.text)))
        if start is None:
            t = tp.find("t:Time", _NS)
            if t is not None and t.text:
                start = datetime.fromisoformat(t.text.replace("Z", "+00:00"))
    sport = root.find(".//t:Activity", _NS)
    return ParsedTrack(track=pts, start_time=start,
                       sport=sport.get("Sport") if sport is not None else None)
