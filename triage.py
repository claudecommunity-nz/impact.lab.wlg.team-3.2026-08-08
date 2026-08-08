"""Turn an incoming report into an assessment.

This is the seam between the plumbing and the interesting part. The server
calls `assess(report)` once per report and stores what comes back; the
dashboard renders it. Replace the body of this module and nothing else has
to change.

The baseline here is deliberately thin: a gazetteer lookup for location,
keyword matching for issue, and three hedging rules for category. It exists
so the pipe runs end to end and so anything cleverer has a number to beat.

Contract
--------
assess(report) -> dict with these keys:

    place        str | None    place name as matched
    lat, lon     float | None  coordinates, None when unlocated
    candidates   list          every gazetteer match; >1 means ambiguous
    ambiguous    bool          same name in more than one place
    issue        str           flooding, slip, road, power, water, tree, other
    category     str           action | verify | awareness
    confidence   float         0.0-1.0, how much to trust this assessment
    incident     str | None    grouping key; reports sharing one are duplicates
    signals      list[str]     human-readable reasons, shown in the interface
    assessed_by  str           which assessor produced this

`signals` is not decoration. The brief asks for reliability to be visible,
so every assessment has to be able to say why it landed where it did.
"""

from __future__ import annotations

import json
import pathlib
import re

ASSESSOR = "baseline-v1"

DATA = pathlib.Path(__file__).parent / "data"

# Longest phrase we bother looking up in the gazetteer. "athlone crescent
# north" is four words; nothing in the corpus is longer.
MAX_PLACE_WORDS = 4

ISSUES = {
    "flooding": ("flood", "water over", "water coming", "surface water", "inundat",
                 "water through", "underwater", "submerged", "awash"),
    "slip": ("slip", "landslide", "slid", "mud", "debris", "bank collapse"),
    "road": ("road closed", "road blocked", "closure", "impassable", "cordon",
             "detour", "blocked"),
    "power": ("power", "outage", "electricity", "lines down", "no power"),
    "water": ("wastewater", "sewage", "water supply", "burst main", "wwtp",
              "treatment plant", "boil water"),
    "tree": ("tree down", "tree across", "fallen tree", "branch"),
}

# Language that marks a report as second-hand or explicitly unconfirmed. The
# corpus is full of it because that is how information actually arrives.
HEDGES = ("someone posted", "word going round", "word is", "reports of",
          "can anyone confirm", "unconfirmed", "heard that", "i heard",
          "apparently", "rumour", "rumor", "not sure if", "someone said",
          "seeing posts", "allegedly", "supposedly")

# Language that means somebody has to do something now.
URGENT = ("trapped", "stranded", "evacuat", "rescue", "people in", "elderly",
          "child", "rising", "getting deeper", "getting worse", "urgent",
          "immediately", "cut off", "can't get out", "cannot get out",
          "help", "injur", "collapsed", "gas")


def _load_places() -> dict:
    with open(DATA / "gazetteer.json") as fh:
        return json.load(fh)["places"]


PLACES = _load_places()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def locate(text: str) -> dict:
    """Find the most specific place name the text mentions.

    Walks every phrase of up to MAX_PLACE_WORDS words and keeps the longest
    gazetteer hit. Longest wins because "konini street" should beat "konini",
    and a street is more useful to a responder than the suburb around it.
    """
    words = _words(text)
    best_key = None
    best_len = 0

    for start in range(len(words)):
        for length in range(min(MAX_PLACE_WORDS, len(words) - start), 0, -1):
            if length <= best_len:
                break
            phrase = " ".join(words[start:start + length])
            if phrase in PLACES:
                best_key, best_len = phrase, length
                break

    if best_key is None:
        return {"place": None, "lat": None, "lon": None,
                "candidates": [], "ambiguous": False}

    entry = PLACES[best_key]
    candidates = entry["candidates"]
    # More than one candidate means the name genuinely exists in several
    # places - Frederick Street is in both Tawa and Te Aro. We do not pick
    # one. Guessing silently is the failure mode this whole problem is about.
    first = candidates[0]
    return {
        "place": entry["name"],
        "lat": first["lat"] if len(candidates) == 1 else None,
        "lon": first["lon"] if len(candidates) == 1 else None,
        "candidates": candidates,
        "ambiguous": len(candidates) > 1,
    }


def classify_issue(text: str) -> str:
    low = text.lower()
    for issue, markers in ISSUES.items():
        if any(marker in low for marker in markers):
            return issue
    return "other"


def categorise(text: str, located: dict) -> tuple[str, list[str]]:
    """Sort into the brief's three buckets, and say why."""
    low = text.lower()
    signals = []

    hedged = [h for h in HEDGES if h in low]
    urgent = [u for u in URGENT if u in low]

    if hedged:
        signals.append(f"second-hand wording: “{hedged[0]}”")
    if urgent:
        signals.append(f"urgency wording: “{urgent[0]}”")
    if located["ambiguous"]:
        signals.append(f"{located['place']} exists in "
                       f"{len(located['candidates'])} places — needs a human")
    elif located["place"] is None:
        signals.append("no location found in the text")

    # Hedged language outranks urgency: a second-hand report of something
    # serious is exactly what needs checking before anyone is dispatched.
    if hedged:
        return "verify", signals
    if located["ambiguous"] or located["place"] is None:
        return "verify", signals
    if urgent:
        return "action", signals
    signals.append("first-hand and located, nothing marking it urgent")
    return "awareness", signals


def confidence(located: dict, issue: str, category: str) -> float:
    score = 0.3
    if located["place"]:
        score += 0.3
    if not located["ambiguous"] and located["lat"] is not None:
        score += 0.2
    if issue != "other":
        score += 0.2
    return round(min(score, 1.0), 2)


def incident_key(located: dict, issue: str) -> str | None:
    """Cheapest defensible duplicate grouping: same issue, same place.

    Reports that share a key describe the same thing. This misses paraphrase
    ("the river's up" vs "flooding on the river") and misses nearby-but-not-
    identical streets. Both are worth fixing; neither is fixed here.
    """
    if not located["place"] or located["ambiguous"]:
        return None
    return f"{issue}:{located['place'].lower()}"


def assess(report: dict) -> dict:
    text = report.get("text", "")
    located = locate(text)
    issue = classify_issue(text)
    category, signals = categorise(text, located)

    return {
        **located,
        "issue": issue,
        "category": category,
        "confidence": confidence(located, issue, category),
        "incident": incident_key(located, issue),
        "signals": signals,
        "assessed_by": ASSESSOR,
    }
