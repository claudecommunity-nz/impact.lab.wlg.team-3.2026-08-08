"""What arrived, from the incidents that caused it.

Each incident becomes a handful of reports on different channels in different
words minutes apart, which is what a duplicate actually looks like. The words
are the only thing a triage tool gets to see; the incident id lives in the
answer key.

Two decisions worth knowing about:

  Channel mix follows the hour. At 3am people ring. Forms and partner job
  records arrive in office hours, which is why the small-hours surge is almost
  entirely voice and social - the hardest possible text, arriving fastest.

  A place is named the way a person would name it. Sometimes with the suburb,
  sometimes as a bare street name, sometimes abbreviated. When the bare name has
  more than one location in the gazetteer the report is marked ambiguous in the
  answer key, because refusing to place it is the right answer and a tool should
  be scored for refusing rather than for guessing.
"""

from __future__ import annotations

import datetime

import voice

# Weights by channel, split at 06:00 and 20:00. Phone and social dominate
# throughout; partner job records stay a minority everywhere because they are
# pre-structured and are the easy case.
NIGHT_MIX = {"phone": 44, "social": 34, "form": 12, "email": 4, "partner": 6}
DAY_MIX = {"phone": 28, "social": 25, "form": 18, "email": 13, "partner": 16}
EVENING_MIX = {"phone": 33, "social": 33, "form": 15, "email": 10, "partner": 9}

# Which agency files a record about what. A lines company does not raise a
# stormwater blockage and the police do not log a water type, and a partner
# record that mixes them up is the one thing in this stream a Council reader
# would spot instantly.
AGENCY_FOR = {
    "flooding": ("water", "fenz"),
    "road": ("police", "fenz"),
    "slip": ("fenz", "police"),
    "water": ("water",),
    "power": ("lines",),
    "tree": ("fenz", "police"),
    "other": ("fenz", "water"),
}

WATER_FAULT_FOR = {
    "flooding": ("Blockage - Significant", "Storm Water"),
    "water": ("Leaking Pipes", "Potable Water"),
    "other": ("General Fault", "Waste Water"),
}

FENZ_TYPE_FOR = {
    "flooding": "Flooding - property", "slip": "Landslide",
    "road": "Hazardous conditions - roadway", "tree": "Tree down",
    "other": "Weather-related callout",
}


def mix_for(hour: int) -> dict[str, int]:
    if hour < 6:
        return NIGHT_MIX
    if hour >= 20:
        return EVENING_MIX
    return DAY_MIX


def pick(rng, weights: dict[str, int]) -> str:
    keys = sorted(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def place_phrases(incident: dict) -> list[tuple[str, bool]]:
    """How people might name this place, and whether the naming is ambiguous.

    Returns (phrase, ambiguous) pairs. A bare street name that exists in several
    suburbs is ambiguous; the same name with its suburb attached is not.
    """
    name, suburb = incident["name"], incident["suburb"]
    if not name:
        return [("", False)]
    multi = incident["multi_candidate"]
    if suburb and suburb != name:
        short = name.replace(" Street", " St").replace(" Road", " Rd")
        return [
            (f"{name}, {suburb}", False),
            (f"{name} in {suburb}", False),
            (f"{name.lower()} {suburb.lower()}", False),
            (name, multi),
            (short, multi),
            (f"the top end of {name}", multi),
        ]
    # A suburb name barely varies in the wild. Nobody posting at 3am writes
    # "Newtown, Wellington" - they write "newtown". The variety in these reports
    # comes from the sentence around the name, not from the name.
    return [(name, False), (name.lower(), False)]


def issue_bank(incident: dict, rng, rumour: bool) -> str:
    """Which phrasing bank a report draws on."""
    if incident["kind"] == "unlocatable":
        return "vague"
    if rumour:
        return "rumour"
    if incident["kind"] == "evacuation":
        return "evacuation" if rng.random() < 0.7 else incident["issue"]
    return incident["issue"]


def partner_text(rng, incident: dict, phrase: str) -> str:
    """A pre-structured job record from whichever agency would have raised it.

    These are the easy case - already structured, already located - which is why
    they are a minority of the stream. Each one carries a street and suburb and
    no house number: the address of a property that flooded is somebody's home.
    """
    issue = incident["issue"]
    agency = rng.choice(AGENCY_FOR.get(issue, AGENCY_FOR["other"]))
    prefix = voice.PARTNER_PREFIX[agency]
    where = phrase or "location not supplied"
    status = rng.choice(["In Queue", "Under Investigation", "In Progress", "New"])

    if agency == "water":
        fault, water_type = WATER_FAULT_FOR.get(issue, WATER_FAULT_FOR["other"])
        priority = rng.choice(["Urgent", "High", "High", "Medium"])
        return (f"{prefix}. {fault}. {where}. {water_type}. {status}. "
                f"Priority {priority}. Reactive Maintenance")
    if agency == "fenz":
        return (f"{prefix}. {FENZ_TYPE_FOR.get(issue, FENZ_TYPE_FOR['other'])}. "
                f"{where}. {rng.randint(1, 3)} appliance(s) attended. "
                f"Referred to Council for follow-up.")
    if agency == "police":
        return (f"{prefix}. {where}. Road closed to traffic, units on scene. "
                f"Requesting Council signage and barriers. {status}.")
    return (f"{prefix}. Unplanned outage. {where}. "
            f"Approximately {rng.choice([15, 40, 60, 150, 220])} customers "
            f"affected. Crew assigned, no restoration estimate.")


def fresh(rng, templates: list[str], used: set[str]) -> str:
    """A template this incident has not used yet.

    Two people reporting the same flood word it differently. If a cluster is
    allowed to reuse a template it produces literally identical reports, and
    then duplicate detection is a string comparison rather than the judgement
    the problem statement is actually about.
    """
    unused = [t for t in templates if t not in used]
    chosen = rng.choice(unused or templates)
    used.add(chosen)
    return chosen


def realise(rng, incident: dict, when: datetime.datetime, late: bool,
            used: set[str]) -> tuple[str, str, str | None, bool]:
    """One report: its channel, text, source url and whether it named ambiguously."""
    phrase, ambiguous = rng.choice(place_phrases(incident))

    if incident["source_urls"] and rng.random() < 0.75:
        return "news", fresh(rng, voice.NEWS, used), rng.choice(
            incident["source_urls"]), False

    channel = pick(rng, mix_for(when.hour))
    if incident["kind"] == "unlocatable":
        channel = pick(rng, {"phone": 55, "social": 30, "form": 10, "email": 5})

    if channel == "partner":
        # An agency record names the place properly. "the top end of Harper
        # Street" is how a caller talks, not how a job gets logged.
        canonical = place_phrases(incident)[0][0]
        return channel, partner_text(rng, incident, canonical), None, False

    if late and channel in voice.LATE:
        return channel, fresh(rng, voice.LATE[channel], used).format(
            place=phrase), None, ambiguous

    rumour = rng.random() < incident["rumour_share"]
    templates = voice.bank(channel, issue_bank(incident, rng, rumour))
    return channel, fresh(rng, templates, used).format(place=phrase), None, ambiguous


def times_for(rng, incident: dict) -> list[tuple[datetime.datetime, bool]]:
    """When each member of a cluster arrived, and whether it is a late one.

    Reports of the same thing do not arrive evenly. The first two or three come
    quickly while it is happening, then the tail stretches - somebody gets home
    and posts about it, somebody else rings when the line frees up.
    """
    out = [(incident["first_at"], False)]
    for i in range(1, incident["size"]):
        lag = rng.randint(1, max(2, incident["spread_min"] * min(i, 3) // 3))
        out.append((incident["first_at"] + datetime.timedelta(minutes=lag), False))
    if incident["straggler"] and incident["size"] > 2:
        out[-1] = (incident["first_at"]
                   + datetime.timedelta(hours=rng.randint(5, 11),
                                        minutes=rng.randint(0, 59)), True)
    return out


def build(rng, incidents: list[dict], last_at: datetime.datetime) -> tuple[list, list]:
    """The whole stream, sorted by arrival, plus the answer key.

    Ids are assigned after sorting, so R0001 really is the first report of the
    night and a demo can be paused at R0100 and mean something.
    """
    pending = []
    # Two reports of different incidents must not come out word for word
    # identical. If they did, a tool that grouped them would be marked wrong for
    # doing the sensible thing, and the score would stop meaning anything.
    seen_texts: set[str] = set()
    for incident in incidents:
        used: set[str] = set()
        for when, late in times_for(rng, incident):
            if when > last_at:
                when = last_at - datetime.timedelta(minutes=rng.randint(0, 40))
            for _ in range(6):
                channel, text, url, ambiguous = realise(rng, incident, when, late, used)
                if text not in seen_texts:
                    break
            seen_texts.add(text)
            pending.append({
                "when": when, "channel": channel, "text": text,
                "source_url": url, "ambiguous": ambiguous, "incident": incident,
                "late": late,
            })

    pending.sort(key=lambda p: (p["when"], p["incident"]["id"], p["text"]))

    reports, key = [], []
    for index, item in enumerate(pending, start=1):
        rid = f"R{index:04d}"
        incident = item["incident"]
        reports.append({
            "id": rid,
            "received_at": item["when"].isoformat(),
            "channel": item["channel"],
            "text": item["text"],
            "source_url": item["source_url"],
            "origin": "generated",
        })
        basis = incident["basis"]
        if item["late"]:
            basis += "; this report arrived hours after the incident"
        key.append({
            "id": rid,
            "incident": incident["id"],
            "true_place": incident["place"],
            "true_lat": incident["lat"],
            "true_lon": incident["lon"],
            "issue": incident["issue"],
            "category": incident["category"],
            "unfounded": incident["unfounded"],
            "ambiguous": item["ambiguous"],
            "basis": basis,
        })
    return reports, key
