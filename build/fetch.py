"""The one place that touches the network.

Two kinds of thing get fetched:

  Real data we keep      the six CAP alerts issued 18-23 April 2026. NEMA's
                         alert layer keeps history, so this is the actual
                         broadcast record for the event, not a reconstruction.

  Schemas we write into  the field definitions for Wellington Water jobs, WCC
                         road closures and electricity outages. No public
                         record exists of what those held on 20 April, so the
                         records are generated - but into the real schema,
                         taken from the live service rather than invented.

Rainfall, river level and transport counts are already frozen in the replay
bundle under `Mark's prep/data/replay/april-2026/`, fetched from Hilltop and
WCC's S3 CSVs when that bundle was built. Re-downloading 180 MB of monthly
count CSVs to slice one day out of them would be a slow way to get the same
numbers, so `observations.py` reads the frozen copies.
"""

from __future__ import annotations

import cache

# NEMA's national CAP alert layer. `historic` is set on alerts that have
# expired, and they stay in the layer, which is what makes April retrievable.
CAP_ALERTS = ("https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/"
              "NZ_CAP_Alerts_(Read_only)/FeatureServer/0")

# The live Wellington Water job layer is index 5. Layer 0 and its similarly
# named neighbours look right and have been dead since 2018.
WATER_FAULTS = ("https://services7.arcgis.com/2ECs938g489DMWjt/arcgis/rest/services/"
                "Job_Status_Public_View/FeatureServer/5")

ROAD_CLOSURES = ("https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/"
                 "StreetEventsAndRoadClosures/MapServer/1")

OUTAGES = ("https://services5.arcgis.com/cJn6oR1QqErYBL5d/arcgis/rest/services/"
           "electricity_outages_read_only/FeatureServer/0")

NEMA = "National Emergency Management Agency"
NEMA_LICENCE = "CC BY 4.0 (NEMA open data)"


def all_sources() -> None:
    print("Fetching. This is the only step that needs network.\n")

    print("  CAP alerts, 18-23 April 2026")
    cap = cache.arcgis(
        "cap-alerts", CAP_ALERTS,
        publisher=NEMA, licence=NEMA_LICENCE,
        where=("sent >= TIMESTAMP '2026-04-18 00:00:00' "
               "AND sent <= TIMESTAMP '2026-04-23 23:59:59'"),
        outFields="*", returnGeometry="false",
    )
    print(f"    {len(cap['payload'].get('features', []))} alerts")

    for name, url, publisher, licence in (
        ("water-faults-schema", WATER_FAULTS, "Wellington Water",
         "Wellington Water open data"),
        ("road-closures-schema", ROAD_CLOSURES, "Wellington City Council",
         "WCC open data"),
        ("outages-schema", OUTAGES, NEMA, NEMA_LICENCE),
    ):
        meta = cache.arcgis_fields(name, url, publisher=publisher, licence=licence)
        fields = meta["payload"]["fields"]
        print(f"  {name}: {len(fields)} fields, {meta['payload']['geometryType']}")

    print("\nCached. Every later build reads these files and needs no network.")
