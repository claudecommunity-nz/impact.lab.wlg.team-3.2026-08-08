"""Resolve a place name mentioned in free text to a coordinate.

Deliberately dumb: longest-name-wins over a local gazetteer. It exists so a
call transcript that says "slip across Ngaio Gorge" can appear on the map at
all. A match is always returned with `method=gazetteer` and a confidence below
1.0, and the UI renders those pins hollow — an inferred location must never
look like a known one.
"""

from __future__ import annotations

import json
import math
import re
import threading
from functools import lru_cache

from ..config import ROOT, get
from ..models import GeoMethod, LocationHint

_lock = threading.Lock()
_places: list[dict] | None = None


def _load() -> list[dict]:
    global _places
    with _lock:
        if _places is not None:
            return _places
        rel = get("settings", "geocode.gazetteer", "data/gazetteer.json")
        path = ROOT / rel
        raw = json.loads(path.read_text()) if path.exists() else {"places": []}
        entries = []
        for place in raw.get("places", []):
            names = [place["name"]] + list(place.get("aliases", []))
            for name in names:
                entries.append({
                    "match": name.lower(),
                    "name": place["name"],
                    "lat": place["lat"],
                    "lon": place["lon"],
                    "kind": place.get("kind", "place"),
                    "suburb": place.get("suburb") or (
                        place["name"] if place.get("kind") == "suburb" else None),
                })
        # Longest names first so "Oriental Parade" beats "Oriental Bay"
        # and "Mount Victoria Tunnel" beats "Mount Victoria".
        entries.sort(key=lambda e: len(e["match"]), reverse=True)
        _places = entries
        return _places


def reload() -> None:
    global _places
    with _lock:
        _places = None
    _load()


# Specificity drives confidence: a street is a better answer than a suburb,
# which is better than "the harbour".
_KIND_CONFIDENCE = {
    "road": 0.62, "landmark": 0.68, "suburb": 0.45,
    "waterway": 0.3, "place": 0.4,
}


def lookup(text: str | None) -> dict | None:
    if not text:
        return None
    hay = re.sub(r"[^a-z0-9\s'-]", " ", text.lower())
    hay = re.sub(r"\s+", " ", hay)
    for entry in _load():
        needle = entry["match"]
        # Word-boundary match so "tawa" doesn't fire inside "tawapou".
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", hay):
            return entry
    return None


def enrich(location: LocationHint | None, *texts: str | None) -> LocationHint | None:
    """Fill in coordinates from free text when none were supplied.

    Never overwrites coordinates that came from a device or an operator.
    """
    if not get("settings", "geocode.enabled", True):
        return location

    if location and location.has_coords:
        if location.suburb is None:
            hit = lookup(location.text) or lookup(" ".join(t for t in texts if t))
            if hit:
                location.suburb = hit["suburb"] or hit["name"]
        return location

    candidates = []
    if location and location.text:
        candidates.append(location.text)
    candidates.extend(t for t in texts if t)

    for text in candidates:
        hit = lookup(text)
        if not hit:
            continue
        confidence = _KIND_CONFIDENCE.get(hit["kind"], 0.4)
        if location is None:
            location = LocationHint()
        location.lat = hit["lat"]
        location.lon = hit["lon"]
        location.method = GeoMethod.gazetteer
        location.confidence = confidence
        location.suburb = hit["suburb"] or hit["name"]
        location.accuracy_m = 900 if hit["kind"] == "suburb" else 350
        if not location.text:
            location.text = hit["name"]
        return location

    return location


def distance_m(a: LocationHint | None, b: LocationHint | None) -> float | None:
    """Haversine. Returns None when either side has no coordinates."""
    if not a or not b or not a.has_coords or not b.has_coords:
        return None
    r = 6_371_000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
