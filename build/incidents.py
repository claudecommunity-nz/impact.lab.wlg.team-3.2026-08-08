"""What actually happened, before anyone reported it.

An incident is a thing at a place at a time. A report is one person's account of
it. Separating the two is what makes duplicate detection measurable: the answer
key can say "these six reports are all incident I014" because I014 was decided
first and the reports were written from it.

Every incident traces to one of three things, and its `basis` says which:

  ground truth   a street recorded as evacuated, a suburb with uninhabitable
                 dwellings, the declaration itself
  the gauges     millimetres recorded at a named gauge in a named hour
  the reporting  the RNZ articles cited in ground-truth.json

Incidents that are none of those do not get made. The one deliberate exception
is the generated infrastructure faults - a burst main is not evidenced by a rain
gauge - and those say so in their basis and are grounded in place by the gauge
nearest them.
"""

from __future__ import annotations

import datetime
import math
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Mark's prep" / "scripts"))
from build_gazetteer import suburb_polygons, which_suburb  # noqa: E402

NZST = datetime.timezone(datetime.timedelta(hours=12))
DAY = datetime.date(2026, 4, 20)

STREET_TYPES = {
    "street", "st", "road", "rd", "avenue", "ave", "grove", "terrace", "tce",
    "crescent", "cres", "place", "pl", "drive", "dr", "lane", "way", "parade",
    "close", "track", "esplanade", "quay", "circuit", "rise", "view", "gardens",
}


def at(hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=NZST)


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return math.hypot((lat1 - lat2) * 110.574,
                      (lon1 - lon2) * 111.320 * math.cos(math.radians(lat1)))


def displace(rng, lat: float, lon: float,
             min_km: float = 0.3, max_km: float = 1.1) -> tuple[float, float]:
    """Move a point a few hundred metres in a random direction.

    An incident is near a gauge, not on it. Generating reports at the gauge's own
    coordinates would make corroboration trivially true - the report would be
    standing on the instrument - and would flatter any result measured from it.
    """
    km = rng.uniform(min_km, max_km)
    bearing = rng.uniform(0, 2 * math.pi)
    return (lat + (km * math.cos(bearing)) / 110.574,
            lon + (km * math.sin(bearing)) / (111.320 * math.cos(math.radians(lat))))


def resolve(gaz: dict, name: str, near_lat: float | None = None) -> dict | None:
    """Best gazetteer candidate for a place name, optionally nearest a hint.

    Falls back to the name body when the exact string misses. People get street
    types wrong constantly: the April reporting said "Wetherby Street", and the
    street in Wainuiomata is Wetherby Grove. Exact matching silently loses that
    incident, which is the failure this whole problem is about.
    """
    place = gaz.get(name.lower())
    if not place:
        body = " ".join(w for w in name.lower().split() if w not in STREET_TYPES)
        matches = [p for k, p in sorted(gaz.items())
                   if body and " ".join(w for w in k.split()
                                        if w not in STREET_TYPES) == body]
        place = matches[0] if matches else None
    if not place:
        return None
    candidates = place["candidates"]
    if near_lat is not None and len(candidates) > 1:
        candidates = sorted(candidates, key=lambda c: abs(c["lat"] - near_lat))
    return {
        "name": place["name"],
        "kind": place["kind"],
        "candidate_count": len(place["candidates"]),
        **candidates[0],
    }


def streets_near(gaz: dict, lat: float, lon: float, within_km: float = 1.6) -> list[dict]:
    """Real street names close to a point, in a stable order.

    Sorted by distance then name so the same seed always picks the same streets.
    """
    found = []
    for key in sorted(gaz):
        place = gaz[key]
        if place["kind"] != "street":
            continue
        candidate = place["candidates"][0]
        distance = km_between(lat, lon, candidate["lat"], candidate["lon"])
        if distance <= within_km:
            found.append({
                "name": place["name"],
                "lat": candidate["lat"],
                "lon": candidate["lon"],
                "candidate_count": len(place["candidates"]),
                "km": distance,
            })
    found.sort(key=lambda s: (round(s["km"], 4), s["name"]))
    return found


class Catalogue:
    """Builds the incident list. One method per kind, so the mix is readable."""

    def __init__(self, rng, gaz: dict, rain: dict, truth: dict):
        self.rng = rng
        self.gaz = gaz
        self.rain = rain["reporting"]
        self.truth = truth
        self.polys = suburb_polygons()
        self.incidents: list[dict] = []
        self._suburbs = self._gauge_suburbs()

    # -- gauges ----------------------------------------------------------

    def _gauge_suburbs(self) -> dict[str, dict]:
        """Gauges that sit inside a named Wellington suburb, with their day.

        Gauges outside the WCC suburb layer - the Hutt River and Porirua Stream
        sites - are left out of this mapping on purpose. The nearest suburb
        centroid to the Birch Lane gauge is Horokiwi, six kilometres away over a
        hill, and naming it that in a report would be an invention dressed as
        geography. Those gauges stay in the observations; they just do not get
        to name a place.
        """
        out = {}
        for name in sorted(self.rain):
            gauge = self.rain[name]
            lat, lon = float(gauge["lat"]), float(gauge["lon"])
            suburb = which_suburb(lat, lon, self.polys)
            if not suburb:
                continue
            out.setdefault(suburb, {
                "suburb": suburb, "gauge": name, "lat": lat, "lon": lon,
                "hourly": self._hourly(gauge),
            })
        return out

    @staticmethod
    def _hourly(gauge: dict) -> dict[int, float]:
        hours: dict[int, float] = {}
        for stamp, mm in gauge["series"]:
            when = datetime.datetime.fromisoformat(stamp)
            if when.date() == DAY:
                hours[when.hour] = round(hours.get(when.hour, 0.0) + mm, 1)
        return hours

    def mm_over(self, suburb: str, first_hour: int, last_hour: int) -> float:
        hours = self._suburbs[suburb]["hourly"]
        return round(sum(v for h, v in hours.items() if first_hour <= h <= last_hour), 1)

    # -- adding ----------------------------------------------------------

    def add(self, *, kind: str, issue: str, category: str, basis: str,
            first_at: datetime.datetime, size: int,
            place: str | None = None, name: str | None = None,
            suburb: str | None = None, lat: float | None = None,
            lon: float | None = None, unfounded: bool = False,
            multi_candidate: bool = False, spread_min: int = 90,
            straggler: bool = False, rumour_share: float = 0.0,
            source_urls: list[str] | None = None) -> dict:
        incident = {
            "id": f"I{len(self.incidents) + 1:03d}",
            "kind": kind, "issue": issue, "category": category,
            "basis": basis, "first_at": first_at, "size": size,
            "place": place, "name": name, "suburb": suburb,
            "lat": lat, "lon": lon, "unfounded": unfounded,
            "multi_candidate": multi_candidate, "spread_min": spread_min,
            "straggler": straggler, "rumour_share": rumour_share,
            "source_urls": source_urls or [],
        }
        self.incidents.append(incident)
        return incident

    # -- the kinds -------------------------------------------------------

    def evacuated_streets(self) -> None:
        """The three Wainuiomata streets recorded as evacuated.

        These are the reports that must reach a human fast, so they get the
        largest clusters: an evacuating street generates calls from several
        households, neighbours, and someone posting about it.

        Wainuiomata sits outside the WCC suburb layer but inside the gazetteer's
        OpenStreetMap pass, which is the only reason these resolve at all.
        """
        hint = -41.2554  # Wainuiomata, to pick the right one of several same-named streets
        for evacuation in self.truth["evacuations"]:
            street = evacuation["street"].split("(")[0].strip()
            suburb = evacuation["suburb"]
            found = resolve(self.gaz, street, near_lat=hint)
            if not found:
                raise RuntimeError(f"ground truth names {street}, gazetteer cannot place it")
            self.add(
                kind="evacuation", issue="flooding", category="action",
                place=f"{found['name']}, {suburb}", name=found["name"], suburb=suburb,
                lat=found["lat"], lon=found["lon"],
                first_at=at(15, self.rng.randint(30, 59))
                + datetime.timedelta(minutes=self.rng.randint(0, 80)),
                size=self.rng.randint(6, 8), spread_min=170,
                multi_candidate=found["candidate_count"] > 1,
                rumour_share=0.25, straggler=True,
                basis=(f"{evacuation['street']}, {suburb} recorded as evacuated in "
                       "contemporaneous reporting of 20 April 2026"),
            )

    def uninhabitable_suburbs(self) -> None:
        """Berhampore, Mornington and South Karori - around ten dwellings.

        Houses were assessed through the afternoon and the assessments landed
        after the declaration, so these cluster in the evening rather than at the
        rain that caused them. That lag is real and it is awkward: the report
        that matters most arrives fourteen hours after the instrument that
        explains it.
        """
        for suburb in self.truth["uninhabitable_dwellings"]["suburbs"]:
            lookup = suburb.replace("South ", "")
            found = resolve(self.gaz, lookup)
            if not found:
                raise RuntimeError(f"ground truth names {suburb}, gazetteer cannot place it")
            issue = self.rng.choice(["flooding", "slip"])
            self.add(
                kind="uninhabitable", issue=issue, category="action",
                place=suburb, name=suburb, suburb=suburb,
                lat=found["lat"], lon=found["lon"],
                first_at=at(16, self.rng.randint(30, 59))
                + datetime.timedelta(minutes=self.rng.randint(0, 90)),
                size=self.rng.randint(5, 8), spread_min=160,
                basis=(f"{suburb} recorded as having dwellings left uninhabitable; "
                       "around ten across the three suburbs"),
            )

    def after_the_declaration(self) -> None:
        """The hour after 17:25, when being told it is serious makes people ring.

        A declaration does not create incidents, it creates reports. People who
        had been coping all day call in, ask where to go, and post about it, and
        a queue that was manageable at 16:00 is not at 17:40. The instruments say
        nothing new in that hour, which is the point: this surge is human, and a
        tool leaning only on corroboration will read it as noise.
        """
        wet = [s for s in sorted(self._suburbs) if self.mm_over(s, 0, 23) >= 40]
        for index in range(10):
            suburb = wet[index % len(wet)]
            site = self._suburbs[suburb]
            streets = streets_near(self.gaz, site["lat"], site["lon"])
            street = self.rng.choice(streets) if streets else None
            issue = self.rng.choice(["flooding", "flooding", "slip", "road", "water"])
            self.add(
                kind="post_declaration", issue=issue,
                category="action" if index % 3 else "verify",
                place=f"{street['name']}, {suburb}" if street else suburb,
                name=street["name"] if street else suburb, suburb=suburb,
                lat=street["lat"] if street else site["lat"],
                lon=street["lon"] if street else site["lon"],
                first_at=at(17, self.rng.randint(25, 59))
                + datetime.timedelta(minutes=self.rng.randint(0, 75)),
                size=self.rng.randint(2, 5), spread_min=80,
                multi_candidate=bool(street) and street["candidate_count"] > 1,
                rumour_share=0.2,
                basis=("reported after the 17:25 declaration; "
                       f"{self.mm_over(suburb, 0, 23):.1f} mm fell at "
                       f"{site['gauge']} over the day"),
            )

    def ambiguous_places(self) -> None:
        """Incidents on streets whose name exists in more than one suburb.

        Wellington has several Rata Streets and the evacuated one is in
        Wainuiomata. Forty-six names in the gazetteer have more than one
        location. When a report names one of them without a suburb there is no
        honest way to place it, and a tool that picks the nearest or the first is
        wrong in a way nobody will notice until it matters.
        """
        for suburb in sorted(self._suburbs):
            site = self._suburbs[suburb]
            if self.mm_over(suburb, 0, 23) < 30:
                continue
            multi = [s for s in streets_near(self.gaz, site["lat"], site["lon"], 2.0)
                     if s["candidate_count"] > 1]
            if not multi:
                continue
            street = multi[0]
            self.add(
                kind="ambiguous_place",
                issue=self.rng.choice(["flooding", "road", "slip"]),
                category="verify",
                place=f"{street['name']}, {suburb}", name=street["name"],
                suburb=suburb, lat=street["lat"], lon=street["lon"],
                first_at=at(self.rng.choice([3, 4, 5, 12, 13, 17, 18]),
                            self.rng.randint(0, 59)),
                size=self.rng.randint(3, 5), spread_min=95,
                multi_candidate=True,
                basis=(f"{street['name']} exists in {street['candidate_count']} "
                       f"places in the gazetteer; this one is in {suburb}, "
                       f"{street['km']:.1f} km from {site['gauge']}"),
            )

    def background(self) -> None:
        """The trickle between the surges.

        A queue is never empty and never uniform. These are the ones and twos
        that arrive through the quiet hours - a tree still down, a road still
        shut, someone getting round to reporting a drain. They exist so the
        demo's quiet stretches look like a real quiet stretch rather than a gap
        in the data.
        """
        wet = [s for s in sorted(self._suburbs) if self.mm_over(s, 0, 23) >= 30]
        quiet_hours = [7, 8, 8, 9, 9, 10, 10, 11, 15, 15, 19, 19, 20, 20, 21, 21]
        for hour in quiet_hours:
            suburb = self.rng.choice(wet)
            site = self._suburbs[suburb]
            streets = streets_near(self.gaz, site["lat"], site["lon"])
            street = self.rng.choice(streets) if streets else None
            issue = self.rng.choice(["road", "tree", "slip", "water", "flooding"])
            self.add(
                kind="background", issue=issue,
                category="verify" if hour > 12 else "action",
                place=f"{street['name']}, {suburb}" if street else suburb,
                name=street["name"] if street else suburb, suburb=suburb,
                lat=street["lat"] if street else site["lat"],
                lon=street["lon"] if street else site["lon"],
                first_at=at(hour, self.rng.randint(0, 59)),
                size=self.rng.randint(1, 3), spread_min=70,
                multi_candidate=bool(street) and street["candidate_count"] > 1,
                basis=(f"{self.mm_over(suburb, 0, 23):.1f} mm recorded at "
                       f"{site['gauge']} over the day"),
            )

    def situation_reports(self) -> None:
        """Partner notices that are context rather than a job.

        A road reopening, a school closing, a centre standing up. Nobody has to
        do anything about them, which is what awareness is for, and a queue with
        none of them makes the three buckets look like two.
        """
        notices = [
            ("Wellington Water", "water", 8,
             "network-wide advisory issued through the day"),
            ("WCC facilities", "other", 9, "facility closure notified for the day"),
            ("Metlink", "road", 7, "service disruption notified for the morning"),
            ("FENZ", "other", 16, "callout volume reported through the afternoon"),
            ("WCC roading", "road", 20, "reopening notified in the evening"),
            ("Wellington Electricity", "power", 21,
             "restoration notified in the evening"),
        ]
        for agency, issue, hour, what in notices:
            suburb = self.rng.choice(sorted(self._suburbs))
            site = self._suburbs[suburb]
            self.add(
                kind="situation_report", issue=issue, category="awareness",
                place=suburb, name=suburb, suburb=suburb,
                lat=site["lat"], lon=site["lon"],
                first_at=at(hour, self.rng.randint(0, 59)),
                size=self.rng.randint(1, 3), spread_min=60,
                basis=f"generated {agency} {what}; no public record of the day's "
                      "notices survives",
            )

    def gauge_backed_flooding(self) -> None:
        """Surface flooding where a gauge proves the rain fell.

        The first-report time follows the gauge: the suburbs that took the 03:00
        downpour generate their reports in the small hours, and the ones that
        took the midday band generate theirs after lunch. That is what makes the
        queue drown twice rather than evenly.
        """
        for suburb in sorted(self._suburbs):
            site = self._suburbs[suburb]
            night = self.mm_over(suburb, 2, 5)
            midday = self.mm_over(suburb, 10, 14)
            if night >= 12:
                peak_hour = max(range(2, 6), key=lambda h: site["hourly"].get(h, 0))
                self._flood_cluster(suburb, site, peak_hour, night, "the four hours to 06:00")
            if midday >= 12:
                peak_hour = max(range(10, 15), key=lambda h: site["hourly"].get(h, 0))
                self._flood_cluster(suburb, site, peak_hour, midday, "the five hours to 15:00")

    def _flood_cluster(self, suburb: str, site: dict, peak_hour: int,
                       mm: float, window: str) -> None:
        heavy = mm >= 45
        lat, lon = displace(self.rng, site["lat"], site["lon"])
        self.add(
            kind="gauge_flooding", issue="flooding",
            category="action" if heavy else "verify",
            place=suburb, name=suburb, suburb=suburb, lat=lat, lon=lon,
            first_at=at(peak_hour, self.rng.randint(5, 59)),
            size=self.rng.randint(4, 8) if heavy else self.rng.randint(2, 5),
            spread_min=120, rumour_share=0.15,
            straggler=heavy,
            basis=(f"{mm:.1f} mm recorded at {site['gauge']} over {window}, "
                   f"peaking in the hour to {peak_hour:02d}:00"),
        )
        # Streets inside the same downpour. A suburb-level report and a
        # street-level one are different incidents even when the rain is the
        # same, and a triage tool has to decide that for itself.
        streets = streets_near(self.gaz, site["lat"], site["lon"])
        if not streets:
            return
        for street in self.rng.sample(streets, min(len(streets), 3 if heavy else 1)):
            self.add(
                kind="street_flooding",
                issue=self.rng.choice(["flooding", "flooding", "road", "slip"]),
                category="action" if heavy else "verify",
                place=f"{street['name']}, {suburb}", name=street["name"], suburb=suburb,
                lat=street["lat"], lon=street["lon"],
                first_at=at(peak_hour, self.rng.randint(0, 59))
                + datetime.timedelta(minutes=self.rng.randint(0, 100)),
                size=self.rng.randint(1, 5) if heavy else self.rng.randint(1, 3),
                spread_min=75,
                multi_candidate=street["candidate_count"] > 1,
                basis=(f"street {street['km']:.1f} km from {site['gauge']}, which "
                       f"recorded {mm:.1f} mm over {window}"),
            )

    def unfounded(self) -> None:
        """Plausible reports placed where every nearby gauge was dry.

        Not "false" - a burst main floods a street on a dry day, and a gauge two
        kilometres away misses a local cell. But they should sort differently
        from the ones the instruments back, and a triage tool that cannot tell
        them apart has not earned its place in the queue.
        """
        wettest = max(self._suburbs, key=lambda s: self.mm_over(s, 2, 5))
        reference = self.mm_over(wettest, 2, 5)
        driest = sorted(self._suburbs, key=lambda s: self.mm_over(s, 2, 5))[:3]
        for suburb in driest:
            site = self._suburbs[suburb]
            mm = self.mm_over(suburb, 2, 5)
            lat, lon = displace(self.rng, site["lat"], site["lon"])
            self.add(
                kind="unfounded", issue="flooding", category="verify",
                place=suburb, name=suburb, suburb=suburb, lat=lat, lon=lon,
                first_at=at(3, self.rng.randint(20, 59)),
                size=self.rng.randint(2, 4), spread_min=110,
                unfounded=True, rumour_share=0.8,
                basis=(f"only {mm:.1f} mm at {site['gauge']} in the four hours to "
                       f"06:00, against {reference:.1f} mm at the "
                       f"{wettest} gauge over the same window"),
            )

    def ahead_of_the_gauge(self) -> None:
        """Reports that arrived before the instruments showed anything.

        Berhampore recorded 3.0 mm in the hour to 02:00 and 77.0 mm in the hour
        to 03:00. Somebody standing in it knew forty minutes before the gauge
        did. A tool that waits for corroboration would have held these back, and
        they were the true ones.
        """
        for suburb in ("Berhampore", "Newtown"):
            if suburb not in self._suburbs:
                continue
            site = self._suburbs[suburb]
            before = site["hourly"].get(2, 0.0)
            during = site["hourly"].get(3, 0.0)
            lat, lon = displace(self.rng, site["lat"], site["lon"])
            self.add(
                kind="ahead_of_gauge", issue="flooding", category="action",
                place=suburb, name=suburb, suburb=suburb, lat=lat, lon=lon,
                first_at=at(2, self.rng.randint(42, 56)),
                size=self.rng.randint(2, 3), spread_min=35,
                basis=(f"arrived before the instrument: {site['gauge']} held "
                       f"{before:.1f} mm in the hour to 02:00 and {during:.1f} mm "
                       "in the hour to 03:00"),
            )

    def infrastructure(self) -> None:
        """Burst mains, outages, trees and closures.

        No public record exists of what broke on the day, so these are generated.
        They are placed inside suburbs the gauges show took heavy rain, and each
        one pairs with a record in the generated feeds, so a prototype can join a
        report to a fault. The basis says plainly that the fault is generated and
        only the rainfall behind it is real.
        """
        plan = [
            ("water", "action", 4), ("power", "action", 6),
            ("tree", "verify", 3), ("road", "action", 3), ("slip", "action", 4),
        ]
        wet = [s for s in sorted(self._suburbs) if self.mm_over(s, 0, 23) >= 40]
        for issue, category, count in plan:
            for _ in range(count):
                suburb = self.rng.choice(wet)
                site = self._suburbs[suburb]
                streets = streets_near(self.gaz, site["lat"], site["lon"])
                street = self.rng.choice(streets) if streets else None
                hour = self.rng.choice([3, 4, 5, 7, 9, 11, 13, 14, 16, 18, 19])
                mm = self.mm_over(suburb, 0, 23)
                self.add(
                    kind=f"generated_{issue}", issue=issue, category=category,
                    place=f"{street['name']}, {suburb}" if street else suburb,
                    name=street["name"] if street else suburb, suburb=suburb,
                    lat=street["lat"] if street else site["lat"],
                    lon=street["lon"] if street else site["lon"],
                    first_at=at(hour, self.rng.randint(0, 59)),
                    size=self.rng.randint(1, 4), spread_min=100,
                    multi_candidate=bool(street) and street["candidate_count"] > 1,
                    basis=(f"generated fault, matched to a record in the generated "
                           f"feeds; the {mm:.1f} mm recorded at {site['gauge']} on "
                           "the day is the only real part of this"),
                )

    def unlocatable(self) -> None:
        """Reports with nothing to place them on.

        A real queue is full of these and they are the ones a naive extractor
        quietly drops. They are kept as incidents with no coordinates so the
        answer key can say a tool was right to refuse rather than wrong to miss.
        """
        for _ in range(8):
            hour = self.rng.choice([3, 3, 4, 4, 6, 11, 15, 17, 17, 18, 20])
            self.add(
                kind="unlocatable", issue="other", category="verify",
                place=None, name=None, suburb=None, lat=None, lon=None,
                first_at=at(hour, self.rng.randint(0, 59)),
                size=self.rng.randint(1, 2), spread_min=45,
                basis="no location stated or obtainable; needs a human or a call back",
            )

    def declaration_and_news(self) -> None:
        """The declaration, the assistance centre, and the reporting of both.

        News arrives already checked by somebody else, which is why it sorts to
        awareness: it is context for the queue, not a job for it.
        """
        sources = self.truth["sources"]
        self.add(
            kind="declaration", issue="other", category="awareness",
            place="Wellington region", name="Wellington", suburb=None,
            lat=None, lon=None,
            first_at=at(17, 25), size=7, spread_min=110,
            source_urls=sources,
            basis="state of emergency declared 17:25 by the Wellington CDEM Group "
                  "joint committee, as reported",
        )
        centre = resolve(self.gaz, "Oxford Terrace")
        self.add(
            kind="assistance_centre", issue="other", category="awareness",
            place="Wellington City Mission, Oxford Terrace",
            name="Oxford Terrace", suburb=None,
            lat=centre["lat"] if centre else None,
            lon=centre["lon"] if centre else None,
            first_at=at(18, self.rng.randint(0, 20)), size=5, spread_min=140,
            source_urls=sources,
            basis="Emergency Assistance Centre opened 18:00 at the Wellington City "
                  "Mission, Oxford Terrace, as reported",
        )
        self.add(
            kind="callouts", issue="other", category="awareness",
            place="Wellington region", name="Wellington", suburb=None,
            lat=None, lon=None,
            first_at=at(16, 30), size=4, spread_min=90,
            source_urls=sources,
            basis="close to 200 weather-related callouts attended from 02:00, "
                  "as reported at 16:30",
        )

    def build(self) -> list[dict]:
        self.evacuated_streets()
        self.ahead_of_the_gauge()
        self.gauge_backed_flooding()
        self.ambiguous_places()
        self.unfounded()
        self.uninhabitable_suburbs()
        self.after_the_declaration()
        self.infrastructure()
        self.background()
        self.unlocatable()
        self.situation_reports()
        self.declaration_and_news()
        return self.incidents
