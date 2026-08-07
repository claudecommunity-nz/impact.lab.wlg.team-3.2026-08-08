"""Verified Wellington emergency data sources, and the small helpers to read them.

Standard library only - no pip install, no virtualenv. Copy this file anywhere.

Every endpoint here was hit and confirmed returning real data. Where a source has
a trap that costs an hour to discover, the trap is recorded next to it rather
than in a wiki nobody opens.
"""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "wellington-impact-lab/1.0 (+hackathon prototype)"
TIMEOUT = 60

# Wellington city bounding box, WGS84. The named-area form of most queries
# returns nothing; the bbox works.
WELLINGTON_BBOX = (174.70, -41.37, 174.95, -41.14)

HILLTOP = "https://hilltop.gw.govt.nz/Telemetry.hts"

# WCC transport sensors. The ArcGIS layer carries only countline geometry; the
# hourly counts live as monthly CSVs on S3.
TRANSPORT_SENSOR_LINES = (
    "https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/"
    "Transport_Sensors/FeatureServer/0"
)
TRANSPORT_S3 = (
    "https://gis-snowflake-opendata-public-wcc-arcgis-prod.s3.ap-southeast-2"
    ".amazonaws.com/transport_sensors"
)


def countline_counts_url(year: int, month: int) -> str:
    """Monthly hourly counts CSV. About 45 MB per month, 1.4M rows."""
    return f"{TRANSPORT_S3}/countline_mobility/csv/{year}/{month:02d}/countline_mobility_{year}_{month:02d}.csv"


COUNTLINE_META_URL = f"{TRANSPORT_S3}/countline_meta_info/csv/countline_meta_info.csv"


def get(url: str, *, timeout: int = TIMEOUT) -> bytes:
    """Fetch bytes with a browser-ish User-Agent, transparently un-gzipping.

    Several Wellington sources (ferries, airport, some council pages) reject a
    bare urllib or curl request but serve fine with a User-Agent set.

    Hilltop gzips some responses whether or not you asked for it, and urllib
    does not decompress unprompted. The body then fails to parse with
    "not well-formed (invalid token): line 1, column 0", which reads like a
    dead endpoint rather than a live one you failed to decode.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body


def get_json(url: str, *, timeout: int = TIMEOUT):
    return json.loads(get(url, timeout=timeout))


class HilltopError(RuntimeError):
    """Hilltop answered, but with an error document rather than data."""


def hilltop(request: str, **params) -> ET.Element:
    """Call the Greater Wellington Hilltop telemetry server.

    Two traps, both of which return something that looks like success:

    1. Spaces in site names must be percent-encoded as %20. A '+' is not decoded
       server-side and yields "No data for site".
    2. A site listed by SiteList is not guaranteed to hold data for your window.
       Decommissioned and sparse gauges answer with <HilltopServer><Error>...,
       which is well-formed XML but not the data schema - a naive parser reading
       <E> elements silently returns an empty series instead of failing.

    Note the root element is not a reliable error signal: GetData succeeds with
    <Hilltop>, SiteList succeeds with <HilltopServer>, and the error document is
    also <HilltopServer>. Only the <Error> child distinguishes them.

    Raises HilltopError for case 2 so callers can tell "no gauge" from "no rain".
    """
    query = urllib.parse.urlencode(
        {"service": "Hilltop", "request": request, **params},
        quote_via=urllib.parse.quote,
    )
    root = ET.fromstring(get(f"{HILLTOP}?{query}"))
    error = root.find("Error")
    if error is not None:
        raise HilltopError((error.text or "unknown Hilltop error").strip())
    return root


def hilltop_series(site: str, measurement: str, start: str, end: str) -> list[tuple[str, float]]:
    """Return [(timestamp, value)] for one gauge. Raises HilltopError if absent."""
    root = hilltop("GetData", Site=site, Measurement=measurement, From=start, To=end)
    out = []
    for e in root.iter("E"):
        t, v = e.findtext("T"), e.findtext("I1")
        if t is None or v is None:
            continue
        try:
            out.append((t, float(v)))
        except ValueError:
            continue
    return out


def hilltop_sites(measurement: str | None = None) -> list[dict]:
    """Sites with coordinates, optionally filtered to those offering a measurement.

    Coordinates come back as WGS84 lat/long directly - no reprojection needed,
    unlike almost everything else in this catalogue.
    """
    params = {"Location": "LatLong"}
    if measurement:
        params["Measurement"] = measurement
    root = hilltop("SiteList", **params)
    sites = []
    for s in root.iter("Site"):
        lat, lon = s.findtext("Latitude"), s.findtext("Longitude")
        if not lat or not lon:
            continue
        sites.append({"name": s.get("Name"), "lat": float(lat), "lon": float(lon)})
    return sites


def in_wellington(site: dict) -> bool:
    w, s, e, n = WELLINGTON_BBOX
    return s < site["lat"] < n and w < site["lon"] < e


def arcgis_query(layer_url: str, **params) -> dict:
    """Query an ArcGIS feature layer, defaulting to WGS84 GeoJSON.

    Services here are natively NZTM2000 (EPSG:2193). Without outSR=4326 you get
    coordinates in the millions and a map centred off the coast of Africa.

    Layers silently cap at maxRecordCount (usually 1000-2000) and set
    exceededTransferLimit rather than erroring. Check it.
    """
    query = {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson", **params}
    url = f"{layer_url}/query?{urllib.parse.urlencode(query, quote_via=urllib.parse.quote)}"
    return get_json(url)


def polite(seconds: float = 0.4):
    """Hilltop and Overpass both rate-limit. Sleep between sequential calls."""
    time.sleep(seconds)
