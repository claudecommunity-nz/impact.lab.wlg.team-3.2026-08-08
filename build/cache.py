"""Fetch once, freeze to disk, never fetch again.

The bundle has to rebuild identically on a laptop with no network, four minutes
before a demo. So every network call goes through here: the response is written
to `build/cache/` with the time it was fetched, and every later build reads the
file instead of the endpoint.

The recorded fetch time travels through to the manifest. That is the honest
answer to "when was this real data collected", and it also keeps the build
deterministic - nothing in the output is stamped with the time you ran it.

    python3 build/build_event.py --fetch    # refresh the cache
    python3 build/build_event.py            # build from it, offline
"""

from __future__ import annotations

import datetime
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Mark's prep" / "scripts"))
import sources  # noqa: E402

CACHE = pathlib.Path(__file__).resolve().parent / "cache"


class MissingCache(RuntimeError):
    """Asked for cached data that was never fetched."""


def path(name: str) -> pathlib.Path:
    return CACHE / f"{name}.json"


def read(name: str) -> dict:
    """The cached payload, with its provenance. Raises if never fetched."""
    p = path(name)
    if not p.exists():
        raise MissingCache(
            f"{p} is missing. Run `python3 build/build_event.py --fetch` once, "
            "on a machine with network."
        )
    return json.loads(p.read_text())


def write(name: str, *, url: str, publisher: str, licence: str, payload) -> dict:
    """Freeze a payload with everything the manifest needs to attribute it."""
    CACHE.mkdir(parents=True, exist_ok=True)
    record = {
        "url": url,
        "publisher": publisher,
        "licence": licence,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
        "payload": payload,
    }
    path(name).write_text(json.dumps(record, indent=1, sort_keys=True))
    return record


def arcgis(name: str, url: str, *, publisher: str, licence: str, **params) -> dict:
    """Fetch an ArcGIS layer into the cache. Only called with --fetch."""
    fc = sources.arcgis_query(url, **params)
    if fc.get("exceededTransferLimit"):
        # Silent capping is the trap that costs an hour here: the layer returns
        # a round number of features and no error at all.
        raise RuntimeError(f"{name}: exceededTransferLimit set - page the query")
    return write(name, url=url, publisher=publisher, licence=licence, payload=fc)


def arcgis_fields(name: str, url: str, *, publisher: str, licence: str) -> dict:
    """Freeze a layer's field definitions.

    Generated records are written into the real schema, so the field list has to
    come from the live service rather than from a guess. Guessing the Wellington
    Water field names in particular yields a row of work-order numbers and
    nothing readable - the descriptive fields are all lowercase.
    """
    meta = sources.get_json(f"{url}?f=json")
    return write(
        name,
        url=f"{url}?f=json",
        publisher=publisher,
        licence=licence,
        payload={
            "name": meta.get("name"),
            "geometryType": meta.get("geometryType"),
            "fields": [
                {"name": f["name"], "type": f["type"], "alias": f.get("alias")}
                for f in meta.get("fields", [])
            ],
        },
    )
