"""Water faults, road closures and outages for 20 April 2026 - all generated.

No public record exists of what Wellington Water, WCC or the lines companies
held open on the day. Those layers publish current state and overwrite it, so
unlike the CAP alerts there is no history to go back for.

So these are generated, and generated into the real schema: the field lists come
from the live services, cached under `build/cache/`, not from a guess. A
prototype that reads these will read the real layers unchanged.

Two things keep that honest:

  The flag sits outside `properties`. Every feature carries "generated": true as
  a sibling of the real field set, so the schema inside `properties` is exactly
  the 30, 10 and 14 fields the live services publish, and the flag cannot be
  mistaken for one of them.

  The text says so too. Each record's human-readable field opens with
  GENERATED RECORD, because the first place anyone looks is the description, and
  a record that reads like a real Council job is precisely the failure these
  problem statements are most wary of.
"""

from __future__ import annotations

import datetime
import math

import cache

FLAG = "GENERATED RECORD - not a real Council or utility job."

WATER_STATUS = ("In Queue", "Under Investigation", "In Progress", "New")
WATER_TYPE_FOR = {
    "water": "Potable Water", "flooding": "Storm Water", "road": "Storm Water",
    "slip": "Storm Water", "tree": "Storm Water", "power": "Storm Water",
    "other": "Waste Water",
}
FAULT_FOR = {
    "water": "Leaking Pipes", "flooding": "Blockage - Significant",
    "road": "General Fault", "slip": "General Fault", "tree": "General Fault",
    "power": "General Fault", "other": "General Fault",
}


def epoch_ms(when: datetime.datetime) -> int:
    return int(when.timestamp() * 1000)


def _fields(name: str) -> tuple[list[str], dict]:
    record = cache.read(name)
    return [f["name"] for f in record["payload"]["fields"]], record


def _envelope(kind: str, record: dict, features: list[dict], note: str) -> dict:
    return {
        "type": "FeatureCollection",
        "origin": "generated",
        "schema_source": record["url"],
        "schema_publisher": record["publisher"],
        "schema_licence": record["licence"],
        "schema_fetched_at": record["fetched_at"],
        "note": note,
        "features": features,
    }


def water_faults(rng, incidents: list[dict]) -> dict:
    """Job records in Wellington Water's 30-field live schema.

    One job per generated infrastructure incident, plus a background of jobs the
    night would have produced anyway. Addresses carry a street and suburb and no
    house number: the address of a property that flooded is somebody's home.
    """
    names, record = _fields("water-faults-schema")
    features = []
    relevant = [i for i in incidents
                if i["kind"].startswith("generated_") or i["kind"] == "street_flooding"]
    for index, incident in enumerate(relevant, start=1):
        if incident["lat"] is None:
            continue
        issue = incident["issue"]
        reported = incident["first_at"] - datetime.timedelta(minutes=rng.randint(5, 50))
        properties = dict.fromkeys(names)
        properties.update({
            "wonum": f"G{900000 + index}",
            "externalrefid": f"GEN{index:07d}",
            "status": rng.choice(["APPR", "INPRG", "INPRG.HD.PAUSE", "RCVD"]),
            "commoditygroup": "CSR",
            "description": f"{FLAG} {FAULT_FOR.get(issue, 'General Fault')} "
                           f"{incident['place']}",
            "reportdate": epoch_ms(reported),
            "actstart": epoch_ms(incident["first_at"]),
            "wsadd_formattedaddress": f"{incident['place']}, Wellington",
            "type": "REPAIR",
            "wtypedesc": "Reactive Maintenance",
            "comm_description": FAULT_FOR.get(issue, "General Fault"),
            "priority": rng.choice(["Urgent", "High", "High", "Medium"]),
            "sourcecode": "Council Integration",
            "source": "GENERATED",
            "councilid": "WCC",
            "watertype": WATER_TYPE_FOR.get(issue, "Storm Water"),
            "privatecheck": "Not private",
            "custservrequestcheck": "Customer Service Request",
            "compdatestatus": "Display",
            "OBJECTID": index,
            "StatusDescription": rng.choice(WATER_STATUS),
        })
        features.append({
            "type": "Feature",
            "generated": True,
            "geometry": {"type": "Point",
                         "coordinates": [round(incident["lon"], 7),
                                         round(incident["lat"], 7)]},
            "properties": properties,
        })
    return _envelope(
        "water", record, features,
        "Generated Wellington Water job records for 20 April 2026, written into "
        "the live layer's 30-field schema. The schema is real and was read from "
        "the service. The jobs are not: no public record of that day survives, "
        "because the layer publishes current state and overwrites it.",
    )


def road_closures(rng, incidents: list[dict]) -> dict:
    """Closures in WCC's 10-field street events schema.

    The real layer is mostly festivals and parades - it is a street events layer
    that road closures happen to live in. A storm closure written into it is the
    right shape and the wrong content for that layer's usual day, which is worth
    knowing before anyone joins the two.
    """
    names, record = _fields("road-closures-schema")
    features = []
    relevant = [i for i in incidents if i["issue"] in ("road", "slip")
                and i["lat"] is not None]
    for index, incident in enumerate(relevant, start=1):
        start = incident["first_at"] + datetime.timedelta(minutes=rng.randint(10, 90))
        end = start + datetime.timedelta(hours=rng.randint(4, 40))
        length_m = rng.randint(120, 900)
        properties = dict.fromkeys(names)
        properties.update({
            "OBJECTID": index,
            "Event_Name": f"Road closure - {incident['place']}",
            "Start_Date": epoch_ms(start),
            "End_Date": epoch_ms(end),
            "EventType": 2,
            "Approved": 1,
            "EventDetails": (
                f"{FLAG} Road closed following "
                f"{'a slip' if incident['issue'] == 'slip' else 'surface flooding'} "
                f"at {incident['place']}. Emergency services access maintained."),
            "Shape.STLength()": float(length_m),
        })
        features.append({
            "type": "Feature",
            "generated": True,
            "geometry": {"type": "MultiLineString",
                         "coordinates": [_segment(rng, incident["lat"],
                                                  incident["lon"], length_m)]},
            "properties": properties,
        })
    return _envelope(
        "closures", record, features,
        "Generated road closures for 20 April 2026 in WCC's 10-field street "
        "events and road closures schema. The schema is real. The closures are "
        "generated and each one is anchored to a generated incident.",
    )


def _segment(rng, lat: float, lon: float, length_m: int) -> list[list[float]]:
    """A short two-point line through a point, for a closure geometry."""
    bearing = rng.uniform(0, math.pi)
    half_km = length_m / 2000
    dlat = (half_km * math.cos(bearing)) / 110.574
    dlon = (half_km * math.sin(bearing)) / (111.320 * math.cos(math.radians(lat)))
    return [[round(lon - dlon, 7), round(lat - dlat, 7)],
            [round(lon + dlon, 7), round(lat + dlat, 7)]]


def outages(rng, incidents: list[dict]) -> dict:
    """Electricity outages in NEMA's 14-field schema.

    numaffected on the real layer is often a count of addresses inside a polygon
    rather than a count of customers off supply, and the layer says which via
    numaffected_source. That distinction is carried through here rather than
    flattened, because "how many people are affected" is exactly the number an
    emergency operations centre will read off a map and act on.
    """
    names, record = _fields("outages-schema")
    features = []
    relevant = [i for i in incidents if i["issue"] == "power" and i["lat"] is not None]
    for index, incident in enumerate(relevant, start=1):
        start = incident["first_at"] - datetime.timedelta(minutes=rng.randint(5, 40))
        end = start + datetime.timedelta(hours=rng.randint(2, 14))
        properties = dict.fromkeys(names)
        properties.update({
            "OBJECTID": index,
            "startdate": epoch_ms(start),
            "enddate": epoch_ms(end),
            "locationname": incident["place"],
            "numaffected": rng.choice([12, 38, 55, 140, 210, 460]),
            "details": f"{FLAG} Unplanned outage attributed to weather damage at "
                       f"{incident['place']}.",
            "status": "Current",
            "outagetype": "Unplanned",
            "distributor": "Wellington Electricity",
            "distributoroutageid": f"GEN-{index:04d}",
            "numaffected_source": "Number of addresses within polygon",
            "numaffected_precision": 2,
        })
        features.append({
            "type": "Feature",
            "generated": True,
            "geometry": {"type": "Point",
                         "coordinates": [round(incident["lon"], 7),
                                         round(incident["lat"], 7)]},
            "properties": properties,
        })
    return _envelope(
        "outages", record, features,
        "Generated electricity outages for 20 April 2026 in NEMA's 14-field "
        "outage schema. The schema is real. The outages are generated. "
        "numaffected counts addresses inside an area, not customers off supply.",
    )
