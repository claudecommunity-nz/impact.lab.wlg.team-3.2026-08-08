# Verified sources

The organisers' catalogue at
<https://github.com/claudecommunity-nz/wcc-emergency-gis-data> covers 74 hazard
layers with per-dataset docs, a dead-ends list and a licensing table. It is
thorough and current. Read `docs/additional-sources.md` there first.

This page holds only two things it does not: sources missing from it, and the
live-feed status check.

## Not in the organisers' catalogue

### WCC transport sensors

The load-bearing source for problem 5, absent from the catalogue entirely.

| | |
|---|---|
| Countline geometry | `https://gis.wcc.govt.nz/arcgis/rest/services/Transportation/Transport_Sensors/FeatureServer/0` - 408 lines, geometry and `COUNTLINE_ID` only |
| Countline metadata | `.../transport_sensors/countline_meta_info/csv/countline_meta_info.csv` - 414 rows with lat/long, direction, first and last data date |
| Hourly counts | `.../transport_sensors/countline_mobility/csv/{year}/{month}/countline_mobility_{year}_{month}.csv` |
| Parquet | `.../transport_sensors/countline_mobility/parquet/countline_mobility.parquet` |

Base: `https://gis-snowflake-opendata-public-wcc-arcgis-prod.s3.ap-southeast-2.amazonaws.com`

Counts run from November 2023 to the current month, refreshed at least monthly.
About 45 MB and 1.4M rows per month. Columns: `COUNTLINE_ID`, `COUNTLINE_DATE`,
`COUNTLINE_HOUR`, `DIRECTION_COUNT`, `COUNTLINE_TRANSPORT_CLASS`, `DIRECTION`.

Classes: Pedestrian, Car, Cyclist, E-scooter, LGV, Motorbike, OGV1, OGV2, Bus.

Owner is WCC's Digital Innovation team, `digitalinnovation@wcc.govt.nz`.

Pōneke Travel Insights, named in the problem statement, is a Council dashboard
rather than a public API. This is the data underneath it.

### RNZ news RSS

`https://www.rnz.co.nz/rss/national.xml` and `/rss/top.xml`. Both live, ~45
items. The catalogue records that WCC's and GWRC's own news RSS 404, but does
not list a working news feed; this is one.

## Live feed status

`scripts/check_feeds.py` probes 19 feeds in about 7 seconds and reports up,
quiet or down. Run it on the day rather than trusting any list, including this
one.

All 19 were up when last run, with these worth noting:

- **Quiet by design**: Civil Defence alert RSS. Empty between events.
- **Populated only during an activation**: GWRC incident areas, WCC Emergency
  Assistance Centres.
- **Largest live corpora**: Wellington Water faults (~1,400 open jobs), WCC
  emergency routes (429 segments), NZTA cameras (319), community hubs (126),
  NEMA alert polygons (108).

## Hilltop telemetry

`https://hilltop.gw.govt.nz/Telemetry.hts` - Greater Wellington's river level,
flow and rainfall. The only genuinely high-cadence local observation.

- Coordinates come back as WGS84 directly. Nothing else here does.
- 51 rainfall gauges are listed inside the Wellington city bbox. In the April
  2026 window only 19 held data.
- Historic retrieval works well back to at least 2016 at full cadence, which is
  what makes replay possible.
- `From` and `To` accept plain `YYYY-MM-DD`.

Measurements worth knowing: `Rainfall` (hourly incremental, mm), `Stage` (river
level, mm), plus soil moisture, wave height and water temperature at some sites.
