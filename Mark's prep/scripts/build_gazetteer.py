#!/usr/bin/env python3
"""Build a place-name to coordinate lookup for Wellington.

Triage needs a location before it can check anything against a rain gauge or an
outage feed, and reports name places in words: "Berhampore", "Rata Street,
Wainuiomata", "the top of Ngaio Gorge".

    python3 scripts/build_gazetteer.py

Writes data/gazetteer.json: suburbs from WCC boundaries, streets from WCC's road
name layer, and streets in the wider region from OpenStreetMap.

The WCC layers stop at the city boundary, which matters here - the April 2026
evacuations were in Wainuiomata, which is Lower Hutt. Without the OSM pass the
gazetteer silently fails on exactly the streets the real event turned on.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import sources  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "gazetteer.json"
SUBURBS = ROOT / "site" / "data" / "suburbs.geojson"

ROADS = "https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/Roads/MapServer/0"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Hutt Valley and Porirua, which the WCC layers do not cover.
WIDER_BBOX = (-41.30, 174.85, -41.10, 175.02)


def log(msg: str) -> None:
    print(msg, flush=True)


def centroid(coords) -> tuple[float, float]:
    """Mean of all positions in an arbitrarily nested coordinate array."""
    xs, ys = [], []

    def walk(node):
        if isinstance(node, list):
            if node and isinstance(node[0], (int, float)):
                xs.append(node[0])
                ys.append(node[1])
            else:
                for child in node:
                    walk(child)

    walk(coords)
    return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)


def cluster(seen: dict[str, list[tuple[float, float]]], source: str) -> dict:
    """Group a name's segments into distinct places rather than averaging them.

    Wellington has several Rata Streets. Averaging their midpoints puts the
    result in none of them - in testing it landed in Naenae, kilometres from the
    Wainuiomata one that mattered. Segments more than roughly 2 km apart are
    treated as different streets that happen to share a name, and both are kept
    so the caller can disambiguate on other evidence in the report.
    """
    out = {}
    for name, points in seen.items():
        groups: list[list[tuple[float, float]]] = []
        for lat, lon in points:
            for g in groups:
                if any(abs(lat - a) < 0.018 and abs(lon - b) < 0.024 for a, b in g):
                    g.append((lat, lon))
                    break
            else:
                groups.append([(lat, lon)])
        out[name.lower()] = {
            "name": name,
            "kind": "street",
            "candidates": [
                {
                    "lat": sum(p[0] for p in g) / len(g),
                    "lon": sum(p[1] for p in g) / len(g),
                    "source": source,
                }
                for g in groups
            ],
        }
    return out


def point_in_ring(lat: float, lon: float, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            xin = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < xin:
                inside = not inside
    return inside


def suburb_polygons() -> list[tuple[str, list]]:
    fc = json.loads(SUBURBS.read_text())
    polys = []
    for f in fc["features"]:
        name = (f["properties"].get("suburb") or "").strip()
        if not name:
            continue
        geom = f["geometry"]
        rings = geom["coordinates"] if geom["type"] == "Polygon" else [
            r for part in geom["coordinates"] for r in part
        ]
        polys.append((name, rings))
    return polys


def which_suburb(lat: float, lon: float, polys) -> str | None:
    for name, rings in polys:
        if rings and point_in_ring(lat, lon, rings[0]):
            return name
    return None


def load_suburbs() -> dict:
    fc = json.loads(SUBURBS.read_text())
    out = {}
    for f in fc["features"]:
        name = (f["properties"].get("suburb") or "").strip()
        if not name:
            continue
        lon, lat = centroid(f["geometry"]["coordinates"])
        out[name.lower()] = {
            "name": name, "kind": "suburb",
            "candidates": [{"lat": lat, "lon": lon, "source": "WCC", "suburb": name}],
        }
    log(f"  {len(out)} suburbs")
    return out


def load_wcc_streets() -> dict:
    """Road name layer, paged - it holds more rows than one request returns."""
    seen: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    offset, page = 0, 1000
    while True:
        fc = sources.arcgis_query(
            ROADS, outFields="full_road_name", resultOffset=offset, resultRecordCount=page
        )
        feats = fc.get("features", [])
        for f in feats:
            name = (f["properties"].get("full_road_name") or "").strip()
            if not name or not f.get("geometry"):
                continue
            lon, lat = centroid(f["geometry"]["coordinates"])
            seen[name].append((lat, lon))
        if len(feats) < page:
            break
        offset += page
    return cluster(seen, "WCC")


def load_osm_streets() -> dict:
    """Named streets in the Hutt Valley and Porirua, from Overpass."""
    s, w, n, e = WIDER_BBOX
    query = f"""
    [out:json][timeout:120];
    way["highway"]["name"]({s},{w},{n},{e});
    out center;
    """
    body = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(
        OVERPASS, data=body, headers={"User-Agent": sources.USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    seen: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    for el in data.get("elements", []):
        name = (el.get("tags", {}).get("name") or "").strip()
        c = el.get("center")
        if not name or not c:
            continue
        seen[name].append((c["lat"], c["lon"]))
    log(f"  {len(seen)} OSM street names in the wider region")
    return cluster(seen, "OSM")


def main() -> int:
    log("Building gazetteer")
    places = {}
    osm = load_osm_streets()
    wcc = load_wcc_streets()
    subs = load_suburbs()
    # Least specific first, so WCC streets beat OSM and suburbs beat both when a
    # name collides - a report saying "Karori" means the suburb, not Karori Road.
    places.update(osm)
    places.update(wcc)
    places.update(subs)

    # Label each candidate with the suburb it falls in, so a report naming both
    # a street and a suburb can pick the right one of several same-named streets.
    polys = suburb_polygons()
    labelled = 0
    for place in places.values():
        for cand in place["candidates"]:
            if "suburb" in cand:
                continue
            suburb = which_suburb(cand["lat"], cand["lon"], polys)
            if suburb:
                cand["suburb"] = suburb
                labelled += 1
    multi = sum(1 for p in places.values() if len(p["candidates"]) > 1)
    log(f"  {labelled} street points located inside a WCC suburb")
    log(f"  {multi} names have more than one distinct location")

    OUT.write_text(json.dumps({
        "places": places,
        "note": (
            "Suburb centroids and street midpoints. A street midpoint is not "
            "where the incident is - it is the best a name alone can do, and for "
            "a long road it can be a kilometre or more out."
        ),
        "attribution": {
            "suburbs and WCC streets": "Wellington City Council",
            "wider region streets": "OpenStreetMap contributors, ODbL",
        },
    }))
    log(f"\nWrote {OUT.relative_to(ROOT)} with {len(places)} places "
        f"({OUT.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
