"""The real half of the bundle: what the instruments and the alert system recorded.

Nothing here is generated. Rainfall, river level and transport counts come from
the frozen replay bundle, sliced to 20 April. CAP alerts come from NEMA's layer,
which keeps expired alerts, so the six issued around the event are the genuine
broadcast record.

These are what the report stream is corroborated against. A caller describing
flooding in Berhampore at 04:00 can be checked against the Berhampore gauge,
which recorded 77 mm in the single hour to 03:00. That check is the whole reason
the observations are in the bundle at all.
"""

from __future__ import annotations

import datetime
import json
import pathlib

import cache

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPLAY = ROOT / "Mark's prep" / "data" / "replay" / "april-2026"

DAY = datetime.date(2026, 4, 20)

GWRC = "Greater Wellington Regional Council"
HILLTOP = "https://hilltop.gw.govt.nz/Telemetry.hts"


def _load(name: str) -> dict:
    return json.loads((REPLAY / name).read_text())


def _on_the_day(series: list) -> list:
    """The 20 April slice of a series, timestamps kept verbatim."""
    out = []
    for stamp, value in series:
        if datetime.datetime.fromisoformat(stamp).date() == DAY:
            out.append([stamp, value])
    return out


def rainfall() -> dict:
    """Hourly rainfall on 20 April for the gauges that were actually reporting.

    The silent gauges are kept as a list rather than dropped. A gauge appearing
    in Hilltop's SiteList for a measurement is not the same as a gauge holding
    data, and a prototype that treats "no reading" as "no rain" is wrong in the
    direction that matters.
    """
    raw = _load("rainfall.json")
    gauges = {}
    for name in sorted(raw["reporting"]):
        gauge = raw["reporting"][name]
        series = _on_the_day(gauge["series"])
        hourly = {}
        for stamp, mm in series:
            hour = datetime.datetime.fromisoformat(stamp).hour
            hourly[hour] = round(hourly.get(hour, 0.0) + mm, 1)
        gauges[name] = {
            "lat": float(gauge["lat"]),
            "lon": float(gauge["lon"]),
            "units": "mm",
            "day_total_mm": round(sum(hourly.values()), 1),
            "peak_hour": max(hourly, key=lambda h: hourly[h]) if hourly else None,
            "peak_hour_mm": round(max(hourly.values()), 1) if hourly else 0.0,
            "hourly_mm": {str(h): hourly[h] for h in sorted(hourly)},
            "series": series,
        }
    return {
        "origin": "real",
        "measurement": "Rainfall (hourly incremental, mm)",
        "date": DAY.isoformat(),
        "publisher": GWRC,
        "source": HILLTOP,
        "reporting": gauges,
        "listed_but_silent": sorted(raw.get("listed_but_silent", [])),
        "note": (
            "Gauges appear in Hilltop's SiteList for a measurement even when they "
            "hold no data for the window. Being listed is not being live, and an "
            "absent reading is not a dry street."
        ),
    }


def river() -> dict:
    """River level on 20 April. Stage is millimetres, not a flood depth."""
    raw = _load("river.json")
    gauges = {}
    for name in sorted(raw["gauges"]):
        gauge = raw["gauges"][name]
        series = _on_the_day(gauge["series"])
        if not series:
            continue
        values = [v for _, v in series]
        peak = max(series, key=lambda sv: sv[1])
        gauges[name] = {
            "units": gauge.get("units", "mm"),
            "min": min(values),
            "max": max(values),
            "rise_over_day": round(values[-1] - values[0], 1),
            "peak_at": peak[0],
            "series": series,
        }
    return {
        "origin": "real",
        "measurement": "Stage (river level, mm above gauge datum)",
        "date": DAY.isoformat(),
        "publisher": GWRC,
        "source": HILLTOP,
        "gauges": gauges,
        "no_data": sorted(raw.get("no_data", [])),
        "note": (
            "Stage is height above the gauge datum, not depth of water on a "
            "street. A rise is evidence a catchment is responding, nothing more."
        ),
    }


def movement() -> dict:
    """Hourly transport counts on 20 April, against a weekday baseline.

    Movement is the independent signal. It has no idea what anyone reported, so
    a collapse in counts on a street somebody phoned about is corroboration that
    did not come from another human.
    """
    raw = _load("movement.json")
    hours = {}
    for key in sorted(raw["window"]):
        date, hour = key.split("T")
        if date != DAY.isoformat():
            continue
        entry = raw["window"][key]
        baseline = raw["baseline"].get(f"{DAY.weekday()}:{int(hour)}", {})
        median = baseline.get("median")
        hours[str(int(hour))] = {
            "total": entry["total"],
            "by_class": dict(sorted(entry["by_class"].items())),
            "baseline_median": median,
            "pct_of_baseline": (round(100 * entry["total"] / median)
                                if median else None),
        }
    day_total = sum(h["total"] for h in hours.values())
    baseline_total = sum(h["baseline_median"] or 0 for h in hours.values())
    return {
        "origin": "real",
        "date": DAY.isoformat(),
        "publisher": "Wellington City Council (Digital Innovation)",
        "source": ("https://gis-snowflake-opendata-public-wcc-arcgis-prod.s3."
                   "ap-southeast-2.amazonaws.com/transport_sensors/"
                   "countline_mobility/csv/2026/04/countline_mobility_2026_04.csv"),
        "countlines": 408,
        "day_total": day_total,
        "baseline_day_total": baseline_total,
        "pct_of_baseline": (round(100 * day_total / baseline_total)
                            if baseline_total else None),
        "exposed_modes": raw.get("exposed_modes", []),
        "enclosed_modes": raw.get("enclosed_modes", []),
        "hourly": hours,
        "note": (
            "Baseline is the median for the same weekday and hour across "
            "February to May, excluding public holidays. A sensor knocked out by "
            "the storm and a street nobody used look identical in this data."
        ),
    }


def cap_alerts() -> dict:
    """The alerts actually broadcast, 18-23 April 2026.

    Only two of the six were issued by the Wellington CDEM Group, and both cover
    Wairarapa rather than Wellington city. That is worth stating plainly: no
    mobile alert was broadcast over the city on the night, so the absence of one
    is not evidence that nothing was happening.
    """
    record = cache.read("cap-alerts")
    alerts = []
    for feature in record["payload"].get("features", []):
        p = feature["properties"]
        alerts.append({
            "identifier": p.get("identifier"),
            "sender_name": p.get("sender_name"),
            "sent": _epoch(p.get("sent")),
            "effective": _epoch(p.get("effective")),
            "expires": _epoch(p.get("expires")),
            "event": p.get("event"),
            "headline": p.get("headline"),
            "description": p.get("description"),
            "severity": p.get("severity"),
            "urgency": p.get("urgency"),
            "certainty": p.get("certainty"),
            "status": p.get("status"),
            "msg_type": p.get("msg_type"),
            "historic": p.get("historic"),
        })
    alerts.sort(key=lambda a: a["sent"] or "")
    wellington = [a for a in alerts
                  if "Wellington" in (a["sender_name"] or "")]
    return {
        "origin": "real",
        "window": "2026-04-18 to 2026-04-23",
        "publisher": record["publisher"],
        "source": record["url"],
        "fetched_at": record["fetched_at"],
        "count": len(alerts),
        "wellington_group_count": len(wellington),
        "alerts": alerts,
        "note": (
            "Emergency Mobile Alerts broadcast nationally in the window. The two "
            "from the Wellington CDEM Group cover Wairarapa, not Wellington city. "
            "No mobile alert went out over the city on 20 April, so absence of an "
            "alert here says nothing about conditions on a given street."
        ),
    }


def _epoch(ms) -> str | None:
    """ArcGIS date fields are epoch milliseconds, UTC. Render them in NZST."""
    if ms is None:
        return None
    nzst = datetime.timezone(datetime.timedelta(hours=12))
    return (datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc)
            .astimezone(nzst).isoformat())
