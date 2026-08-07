#!/usr/bin/env python3
"""Check which live Wellington emergency feeds are up, and what they hold.

Run this first thing on the day. It answers the two questions that otherwise
cost an hour each: is the endpoint alive, and does it currently contain
anything?

The second question matters more than it looks. Several of these feeds are
empty by design between emergencies - that is correct behaviour, not a fault,
and a prototype that treats empty as broken will be debugged pointlessly. Those
are marked "quiet ok" below.

    python3 scripts/check_feeds.py
    python3 scripts/check_feeds.py --json > feeds.json
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sources  # noqa: E402

ARCGIS_COUNT = "/query?where=1%3D1&returnCountOnly=true&f=json"

# name, url, kind, quiet_ok, note
FEEDS = [
    ("GeoNet quakes (MMI>=3)", "https://api.geonet.org.nz/quake?MMI=3",
     "geojson", True, "Filter out quality='deleted' - retractions appear inline"),
    ("GeoNet felt reports", "https://api.geonet.org.nz/intensity?type=reported",
     "geojson", True, "Crowdsourced; compare with type=measured"),
    ("Wellington harbour sea level", "https://tilde.geonet.org.nz/v4/data/coastal/WLGT/water-height-detided/40/15s/nil/latest/6h",
     "json", False, "Detided residual - thresholding it is a surge detector"),
    ("MetService warnings (CAP)", "https://services.arcgis.com/XTtANUDT8Va4DLwI/arcgis/rest/services/Metservice_Weather_Alerts/FeatureServer/0",
     "arcgis", True, "Licence-safe route; the metservice.com JSON is demo-only"),
    ("NEMA mobile alert polygons", "https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/NZ_CAP_Alerts_(Read_only)/FeatureServer/0",
     "arcgis", False, "Live and historic share the layer - filter on 'historic'"),
    ("NEMA electricity outages", "https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/electricity_outages_read_only/FeatureServer/0",
     "arcgis", True, "18 lines companies nationally"),
    ("Wellington Electricity outages", "https://www.welectricity.co.nz/outages/getalloutages",
     "json", True, "Domain is welectricity.co.nz, not wellingtonelectricity"),
    ("Wellington Water faults", "https://services7.arcgis.com/2ECs938g489DMWjt/arcgis/rest/services/Job_Status_Public_View/FeatureServer/5",
     "arcgis", False, "Live layer is index 5, not 0"),
    ("GWRC incident areas", "https://services2.arcgis.com/RS7BXJAO6ksvblJm/arcgis/rest/services/GWRC_EM_Incident_Areas_Layer_View/FeatureServer/0",
     "arcgis", True, "Populated only during an activation"),
    ("Civil Defence alert RSS", "https://alerthub.civildefence.govt.nz/rss/pwp",
     "rss", True, "Empty between events is normal"),
    ("NZTA traffic cameras", "https://www.journeys.nzta.govt.nz/assets/map-data-cache/cameras.json",
     "json", False, "Check Offline and UnderMaintenance before showing an image"),
    ("NZTA delays", "https://www.journeys.nzta.govt.nz/assets/map-data-cache/delays.json",
     "json", True, "Companion to the camera feed"),
    ("WCC road closures", "https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/StreetEventsAndRoadClosures/MapServer/1",
     "arcgis", True, "Includes planned events, not only incidents"),
    ("WCC transport sensor lines", sources.TRANSPORT_SENSOR_LINES,
     "arcgis", False, "Geometry only; hourly counts are monthly CSVs on S3"),
    ("Community emergency hubs", "https://mapping.gw.govt.nz/arcgis/rest/services/GW/Emergencies_P/MapServer/2",
     "arcgis", False, "CC BY-NC-ND 4.0 - the one restrictive licence"),
    ("WCC emergency routes", "https://services1.arcgis.com/CPYspmTk3abe6d7i/arcgis/rest/services/Emergency_Routes/FeatureServer/0",
     "arcgis", False, "Consult WCC before shipping anything public"),
    ("2degrees mobile outages", "https://api.2degrees.nz/outages/publishedOutages",
     "json", True, "Only public telco outage feed that is a plain GET"),
    ("RNZ national news RSS", "https://www.rnz.co.nz/rss/national.xml",
     "rss", False, "WCC and GWRC news RSS both 404 - this is the working one"),
    ("Hilltop rainfall (live)", None, "hilltop", False,
     "Gauges listed for a measurement may still hold no data"),
]


def count_arcgis(url: str) -> tuple[int | None, str]:
    data = sources.get_json(url + ARCGIS_COUNT)
    if "count" in data:
        return data["count"], "records"
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "arcgis error"))
    return None, "unknown"


def count_json(url: str) -> tuple[int | None, str]:
    data = sources.get_json(url)
    if isinstance(data, dict):
        for key in ("features", "outages", "data", "results", "items"):
            if isinstance(data.get(key), list):
                return len(data[key]), key
        return len(data), "keys"
    if isinstance(data, list):
        return len(data), "items"
    return None, "unknown"


def count_rss(url: str) -> tuple[int | None, str]:
    root = ET.fromstring(sources.get(url))
    items = root.findall(".//item") or root.findall(
        ".//{http://www.w3.org/2005/Atom}entry"
    )
    return len(items), "items"


def count_hilltop() -> tuple[int | None, str]:
    """How many Wellington rainfall gauges reported in the last six hours."""
    sites = [s for s in sources.hilltop_sites("Rainfall") if sources.in_wellington(s)]
    return len(sites), "gauges listed"


def check(feed) -> dict:
    name, url, kind, quiet_ok, note = feed
    started = time.time()
    try:
        if kind == "arcgis":
            count, unit = count_arcgis(url)
        elif kind == "json":
            count, unit = count_json(url)
        elif kind == "geojson":
            count, unit = count_json(url)
        elif kind == "rss":
            count, unit = count_rss(url)
        elif kind == "hilltop":
            count, unit = count_hilltop()
        else:
            raise RuntimeError(f"unknown kind {kind}")
        status = "up"
        if count == 0:
            status = "quiet" if quiet_ok else "EMPTY"
    except Exception as exc:  # noqa: BLE001 - a failed probe is a result
        return {
            "name": name, "status": "DOWN", "error": str(exc)[:120],
            "ms": int((time.time() - started) * 1000), "note": note, "url": url,
        }
    return {
        "name": name, "status": status, "count": count, "unit": unit,
        "ms": int((time.time() - started) * 1000), "note": note, "url": url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, FEEDS))

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    symbol = {"up": "  up  ", "quiet": " quiet", "EMPTY": " EMPTY", "DOWN": " DOWN "}
    print(f"{'feed':32}{'status':8}{'holds':>12}   {'ms':>6}")
    print("-" * 72)
    for r in sorted(results, key=lambda r: (r["status"] != "DOWN", r["name"])):
        holds = "-" if r.get("count") is None else f"{r['count']:,}"
        print(f"{r['name'][:31]:32}{symbol[r['status']]:8}{holds:>12}   {r['ms']:>6}")
        if r["status"] == "DOWN":
            print(f"{'':32}  {r['error']}")

    down = [r for r in results if r["status"] == "DOWN"]
    empty = [r for r in results if r["status"] == "EMPTY"]
    quiet = [r for r in results if r["status"] == "quiet"]
    print(f"\n{len(results) - len(down)}/{len(results)} up.")
    if quiet:
        print(f"{len(quiet)} quiet (empty is expected between emergencies): "
              + ", ".join(r["name"] for r in quiet))
    if empty:
        print(f"{len(empty)} unexpectedly empty: " + ", ".join(r["name"] for r in empty))
    if down:
        print(f"{len(down)} down: " + ", ".join(r["name"] for r in down))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
