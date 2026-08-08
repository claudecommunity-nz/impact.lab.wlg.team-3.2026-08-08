"""Demo corpus: a Wellington southerly storm, mid-evening.

Everything here is INVENTED. No real person, phone number, address or social
account appears. Reporter names are synthetic and the agency addresses are the
dummy ones from config/destinations.yaml.

The corpus is deliberately messy in the ways a real queue is messy:

* one slip described three different ways by three different channels;
* a tsunami rumour that spreads across social media and is false;
* a life-safety call that nobody on the night shift ever opened — which is the
  case the shift handover exists to catch;
* two reportings forwarded to FENZ with no reply yet.

Seeding also plays back a partly-worked night shift so the audit trail and the
handover briefing have something real to show immediately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import audit as audit_mod
from . import db, forward
from .models import Priority, Status
from .triage import engine
from .ingest import to_reporting

NZ = timezone(timedelta(hours=12))

NIGHT = "night.controller"
DAY = "day.controller"


def _t(minutes_ago: int) -> str:
    return (datetime.now(NZ) - timedelta(minutes=minutes_ago)).isoformat()


# ---------------------------------------------------------------------------
# the corpus: (adapter_id, payload) in each source system's own shape
# ---------------------------------------------------------------------------


def _corpus() -> list[tuple[str, dict[str, Any]]]:
    return [
        # -- Cluster A: slip on Ngaio Gorge, three channels -------------------
        ("call_centre", {
            "call_id": "CC-4471", "call_started_at": _t(196),
            "call_reason": "Slip blocking road",
            "transcript": ("Caller says a big slip has come down across Ngaio "
                           "Gorge Road, about halfway down. Mud and rocks right "
                           "across both lanes, no one can get through. No cars "
                           "caught in it that she can see. Getting worse, more "
                           "coming down off the bank."),
            "caller_stated_location": "Ngaio Gorge",
            "caller_name": "A. Whitcombe", "caller_phone": "04 555 0142",
            "caller_is_agency": False,
        }),
        ("social_media", {
            "post_id": "sm-88213", "platform": "x",
            "url": "https://example.invalid/post/88213", "posted_at": _t(188),
            "text": "Ngaio Gorge is completely blocked, huge slip across the road. "
                    "Do not try it, turn around at the top. #wgtn",
            "author": {"handle": "@ngaio_local", "display_name": "Ngaio Local",
                       "verified": False, "is_official": False,
                       "follower_count": 640, "account_age_days": 2900},
            "media": [{"type": "image", "url": "https://example.invalid/img/88213.jpg",
                       "alt_text": "Mud and rock across a road",
                       "model_caption": "Debris covering both lanes of a hill road at night"}],
            "geo": {"place_name": "Ngaio Gorge", "source": "text_inference"},
            "engagement": {"reposts": 41, "likes": 88, "replies": 12},
            "credibility": 0.4, "language": "en",
        }),
        ("partner_agency", {
            "agency": "WCC Roading", "reference": "RD-2026-0812",
            "issued_at": _t(150), "title": "Ngaio Gorge Road closed",
            "detail": "Slip across Ngaio Gorge Road confirmed by crew on site. "
                      "Road closed both directions. Detour via Khandallah. "
                      "Geotech assessment required before reopening.",
            "location_description": "Ngaio Gorge Road",
            "location": {"lat": -41.2570, "lon": 174.7770},
            "contact": "Roading duty officer",
            "link": "https://example.invalid/wcc/rd-2026-0812",
        }),

        # -- Cluster B: flooding through Newtown ------------------------------
        ("call_centre", {
            "call_id": "CC-4488", "call_started_at": _t(142),
            "call_reason": "Flooding",
            "transcript": ("Water is coming up over the footpath on Adelaide Road "
                           "near the shops and starting to come in the front door "
                           "of the ground floor flats. It's rising fast, it was "
                           "only at the kerb twenty minutes ago. There's an elderly "
                           "couple downstairs."),
            "caller_stated_location": "Adelaide Road, Newtown",
            "caller_name": "M. Paretoa", "caller_phone": "021 555 0198",
        }),
        ("web_form", {
            "submission_id": "WF-9902", "submitted_at": _t(131),
            "issue_type": "Flooding", "observed_at": _t(136),
            "description": "Surface water flooding across Riddiford Street outside "
                           "the shops, about ankle deep and getting worse. Drains "
                           "look blocked with leaves.",
            "address": "Riddiford Street, Newtown",
            "geo": {"lat": -41.3091, "lng": 174.7788, "accuracy": 18},
            "contact_name": "J. Rewi", "contact_email": "j.rewi@example.invalid",
            "photos": [{"url": "https://example.invalid/img/wf9902.jpg",
                        "caption": "Water across the street outside the shops"}],
        }),
        ("social_media", {
            "post_id": "sm-88377", "platform": "bluesky",
            "url": "https://example.invalid/post/88377", "posted_at": _t(120),
            "text": "Newtown is flooding again. Adelaide Rd is a river. "
                    "Drains never cope.",
            "author": {"handle": "@newtownwatch", "display_name": "Newtown Watch",
                       "verified": False, "is_official": False,
                       "follower_count": 2100, "account_age_days": 1500},
            "geo": {"place_name": "Newtown", "source": "text_inference"},
            "credibility": 0.45, "language": "en",
        }),

        # -- Cluster C: sea wall overtopping, Oriental Parade ------------------
        ("social_media", {
            "post_id": "sm-88401", "platform": "x",
            "url": "https://example.invalid/post/88401", "posted_at": _t(112),
            "text": "Waves coming right over the sea wall onto Oriental Parade, "
                    "spray hitting the buildings. Wouldn't walk along there tonight.",
            "author": {"handle": "@harbourside", "display_name": "Harbourside",
                       "verified": True, "is_official": False,
                       "follower_count": 8800, "account_age_days": 3400},
            "media": [{"type": "video", "url": "https://example.invalid/vid/88401.mp4",
                       "thumbnail": "https://example.invalid/vid/88401.jpg",
                       "alt_text": "Waves over a sea wall"}],
            "geo": {"lat": -41.2916, "lng": 174.7907, "place_name": "Oriental Parade",
                    "source": "post_geotag"},
            "engagement": {"reposts": 210, "likes": 640, "replies": 33},
            "credibility": 0.62, "language": "en",
        }),
        ("news", {
            "guid": "news-5521", "outlet": "Capital Times",
            "link": "https://example.invalid/news/5521", "published_at": _t(96),
            "headline": "Southerly swell closes Oriental Parade lanes",
            "summary": "Wellington City Council has closed the seaward lane of "
                       "Oriental Parade after waves began overtopping the sea "
                       "wall this evening. Motorists are advised to avoid the "
                       "waterfront.",
            "dateline": "Oriental Bay",
        }),

        # -- Cluster D: a tsunami rumour, which is false -----------------------
        ("social_media", {
            "post_id": "sm-88450", "platform": "facebook",
            "url": "https://example.invalid/post/88450", "posted_at": _t(88),
            "text": "Someone said there's a tsunami warning for Wellington "
                    "harbour, everyone get to high ground!!",
            "author": {"handle": "@wgtn_updates_unofficial",
                       "display_name": "Wellington Updates",
                       "verified": False, "is_official": False,
                       "follower_count": 340, "account_age_days": 60},
            "geo": {"place_name": "Wellington Harbour", "source": "text_inference"},
            "engagement": {"reposts": 480, "likes": 120, "replies": 200},
            "credibility": 0.1, "language": "en",
        }),
        ("social_media", {
            "post_id": "sm-88462", "platform": "x",
            "url": "https://example.invalid/post/88462", "posted_at": _t(83),
            "text": "I heard there's a tsunami warning for the harbour? Can anyone "
                    "confirm, my mate said it's on Facebook",
            "author": {"handle": "@te_aro_j", "display_name": "J",
                       "verified": False, "is_official": False,
                       "follower_count": 95, "account_age_days": 800},
            "geo": {"place_name": "Wellington Harbour", "source": "text_inference"},
            "credibility": 0.08, "language": "en",
        }),
        ("social_media", {
            "post_id": "sm-88479", "platform": "facebook",
            "url": "https://example.invalid/post/88479", "posted_at": _t(41),
            "text": "Apparently a tsunami warning is out for Wellington harbour, "
                    "people are saying get to high ground now",
            "author": {"handle": "@porirua_chat", "display_name": "Porirua Chat",
                       "verified": False, "is_official": False,
                       "follower_count": 1200, "account_age_days": 400},
            "geo": {"place_name": "Wellington Harbour", "source": "text_inference"},
            "credibility": 0.12, "language": "en",
        }),

        # -- standalone life-safety calls -------------------------------------
        ("call_centre", {
            "call_id": "CC-4502", "call_started_at": _t(74),
            "call_reason": "Vehicle in floodwater",
            "transcript": ("There's a car stuck in the water on Karori Road near "
                           "the stream and I think there's still someone inside, "
                           "they can't get out, the water is up to the doors. "
                           "Please hurry."),
            "caller_stated_location": "Karori Road near the stream",
            "caller_name": "T. Oliphant", "caller_phone": "027 555 0176",
        }),
        ("call_centre", {
            "call_id": "CC-4509", "call_started_at": _t(63),
            "call_reason": "Smell of gas",
            "transcript": ("Strong smell of gas on Cuba Street outside the old "
                           "building where the scaffolding is. It's quite strong, "
                           "a few of us can smell it. Some bricks came off the "
                           "facade earlier in the wind."),
            "caller_stated_location": "Cuba Street",
            "caller_name": "R. Duffield", "caller_phone": "04 555 0133",
        }),
        # The one nobody opens. Left unacknowledged on purpose.
        ("call_centre", {
            "call_id": "CC-4515", "call_started_at": _t(58),
            "call_reason": "Welfare — power dependent",
            "transcript": ("I'm calling about my mother in Island Bay, she's on "
                           "oxygen at home and the power has been out for two "
                           "hours. The concentrator has a battery but it won't "
                           "last the night. She's 84 and on her own."),
            "caller_stated_location": "Island Bay",
            "caller_name": "H. Mataira", "caller_phone": "021 555 0187",
        }),
        ("call_centre", {
            "call_id": "CC-4521", "call_started_at": _t(34),
            "call_reason": "Person in the water",
            "transcript": ("Someone's gone into the water off the wharf at Petone "
                           "foreshore, there's people on the beach shouting. I "
                           "can't tell if they've got them out."),
            "caller_stated_location": "Petone foreshore",
            "caller_name": "Anonymous caller",
        }),

        # -- infrastructure and welfare ---------------------------------------
        ("email_inbox", {
            "message_id": "<em-7781@example.invalid>", "date": _t(160),
            "from": "faults@example.invalid", "from_name": "Wellington Water Faults",
            "organisation": "Wellington Water",
            "subject": "Water main burst — Johnsonville",
            "body_text": "Crew dispatched to a burst main on Broderick Road, "
                         "Johnsonville. Expect low pressure across Johnsonville "
                         "and Newlands for the next 4 hours. No supply loss "
                         "expected at this stage.",
            "stated_location": "Johnsonville",
        }),
        ("email_inbox", {
            "message_id": "<em-7802@example.invalid>", "date": _t(101),
            "from": "office@example.invalid", "from_name": "Brooklyn School office",
            "organisation": "Brooklyn School",
            "subject": "Roof damage — school will not open tomorrow",
            "body_text": "Wind has lifted part of the roof over the hall. No one "
                         "was on site. We will not open tomorrow. Advising "
                         "families tonight. Passing on for your awareness.",
            "stated_location": "Brooklyn",
            "attachments": [{"url": "https://example.invalid/img/roof.jpg",
                             "filename": "hall-roof.jpg",
                             "content_type": "image/jpeg"}],
        }),
        ("web_form", {
            "submission_id": "WF-9915", "submitted_at": _t(118),
            "issue_type": "Tree down",
            "description": "Large tree down across Karori Road blocking one lane, "
                           "branches on the power lines above it.",
            "address": "Karori Road", "geo": {"lat": -41.2841, "lng": 174.7423,
                                              "accuracy": 25},
            "contact_name": "S. Ngatai", "contact_phone": "021 555 0164",
        }),
        ("social_media", {
            "post_id": "sm-88355", "platform": "mastodon",
            "url": "https://example.invalid/post/88355", "posted_at": _t(126),
            "text": "Power's out across Khandallah, whole street is dark. "
                    "Anyone else?",
            "author": {"handle": "@khandallah_k", "display_name": "K",
                       "verified": False, "is_official": False,
                       "follower_count": 210, "account_age_days": 1100},
            "geo": {"place_name": "Khandallah", "source": "profile"},
            "credibility": 0.35, "language": "en",
        }),
        ("social_media", {
            "post_id": "sm-88500", "platform": "x",
            "url": "https://example.invalid/post/88500", "posted_at": _t(29),
            "text": "I heard the hospital has lost power, someone posted it in a "
                    "group chat. Not sure if true.",
            "author": {"handle": "@te_aro_j", "display_name": "J",
                       "verified": False, "is_official": False,
                       "follower_count": 95, "account_age_days": 800},
            "geo": {"place_name": "Wellington Regional Hospital",
                    "source": "text_inference"},
            "credibility": 0.1, "language": "en",
        }),
        ("partner_agency", {
            "agency": "Fire and Emergency NZ", "reference": "FENZ-88214",
            "issued_at": _t(70), "title": "Multiple weather-related callouts",
            "detail": "FENZ Wellington responding to 14 weather-related incidents, "
                      "mostly trees and roofs. Two appliances committed at Ngaio. "
                      "Capacity constrained for non-life-safety tasks tonight.",
            "location_description": "Wellington",
            "location": {"lat": -41.2865, "lon": 174.7762},
            "contact": "FENZ Wellington comms",
        }),
        ("partner_agency", {
            "agency": "Greater Wellington Regional Council", "reference": "GW-3391",
            "issued_at": _t(48), "title": "Hutt River level rising",
            "detail": "Te Awa Kairangi / Hutt River at Taita Gorge continuing to "
                      "rise. Currently below stopbank design level. Next update "
                      "in one hour.",
            "location_description": "Hutt River",
            "contact": "GW flood duty officer",
        }),

        # -- low value, to prove the bottom of the queue is also sorted -------
        ("social_media", {
            "post_id": "sm-88510", "platform": "x",
            "url": "https://example.invalid/post/88510", "posted_at": _t(22),
            "text": "Thoughts and prayers to everyone out in this weather tonight, "
                    "stay safe everyone!! Great work to the crews out there",
            "author": {"handle": "@kind_wgtn", "display_name": "Kind Wellington",
                       "verified": False, "is_official": False,
                       "follower_count": 3200, "account_age_days": 2000},
            "credibility": 0.3, "language": "en",
        }),
        ("news", {
            "guid": "news-5530", "outlet": "Regional Herald",
            "link": "https://example.invalid/news/5530", "published_at": _t(55),
            "headline": "Severe weather warning remains in place for Wellington",
            "summary": "MetService has extended the severe weather warning for "
                       "Wellington and the Hutt Valley until 6am. Gusts of up to "
                       "130km/h have been recorded on the south coast.",
            "dateline": "Wellington",
        }),
        ("email_inbox", {
            "message_id": "<em-7830@example.invalid>", "date": _t(15),
            "from": "hub.coordinator@example.invalid",
            "from_name": "Kilbirnie hub coordinator",
            "organisation": "Community Emergency Hub",
            "subject": "Kilbirnie hub open, 12 people in",
            "body_text": "We have opened the Kilbirnie hub. Twelve people here so "
                         "far, mostly from flats with no power. We have tea and "
                         "blankets. Two people asking about medication.",
            "stated_location": "Kilbirnie",
        }),
    ]


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------


def _find(reportings: list, needle: str):
    """Locate a seeded reporting by a distinctive phrase."""
    needle = needle.lower()
    for r in reportings:
        if needle in (r.effective_text() or "").lower():
            return r
    return None


def _demo_timetable() -> str:
    """An administrative timetable anchored to the present moment.

    The static example in data/obligations.example.json carries real dates and
    is the documented shape. For a demo, absolute dates land as a wall of
    overdue rows, which shows the styling but not the behaviour — so the seeded
    one is spread around now: a couple already missed, one due in minutes, the
    rest ahead.
    """
    import json

    def at(minutes: int) -> str:
        return (datetime.now(NZ) + timedelta(minutes=minutes)).isoformat()

    return json.dumps({"obligations": [
        {"id": "BR-001", "type": "handover", "short_label": "handover",
         "label": "Shift handover briefing — day to night (OP-1)",
         "due_at": at(-215), "owner_role": "Control", "audience": "internal",
         "score_bearing": False, "shift_ref": "SH-N1",
         "notes": "Previous shift. The crew on duty now came on here."},
        {"id": "BR-002", "type": "sitrep", "short_label": "sitrep",
         "label": "Situation report to Regional EOC — OP-1",
         "due_at": at(-38), "owner_role": "Intelligence", "audience": "external",
         "score_bearing": True, "shift_ref": "SH-N1",
         "notes": "Regional expects this on the hour. Late submission is scored."},
        {"id": "BR-003", "type": "public_update", "short_label": "public update",
         "label": "Public information update — road closures and evacuation centres",
         "due_at": at(9), "owner_role": "PIM", "audience": "public",
         "score_bearing": True, "shift_ref": "SH-N1",
         "notes": "Coordinate wording with Roading before release. "
                  "Ngaio Gorge and Oriental Parade both need a line."},
        {"id": "BR-004", "type": "welfare_check", "short_label": "welfare",
         "label": "Welfare status roll-up from community hubs",
         "due_at": at(47), "owner_role": "Welfare", "audience": "internal",
         "score_bearing": True, "shift_ref": "SH-N1",
         "notes": "Kilbirnie, Brooklyn and Island Bay to report headcount and unmet needs."},
        {"id": "BR-005", "type": "briefing", "short_label": "briefing",
         "label": "All-of-EOC briefing — next operational period objectives",
         "due_at": at(95), "owner_role": "Control", "audience": "internal",
         "score_bearing": False, "shift_ref": "SH-N1"},
        {"id": "BR-006", "type": "sitrep", "short_label": "sitrep",
         "label": "Situation report to Regional EOC — OP-2",
         "due_at": at(200), "owner_role": "Intelligence", "audience": "external",
         "score_bearing": True, "shift_ref": "SH-D1"},
        {"id": "BR-007", "type": "handover", "short_label": "handover",
         "label": "Shift handover briefing — night to day (OP-2)",
         "due_at": at(320), "owner_role": "Control", "audience": "internal",
         "score_bearing": False, "shift_ref": "SH-D1"},
    ]}, indent=2)


def seed_demo(reset: bool = True, use_llm: bool = False,
              scenario: str = "storm") -> dict:
    """Load the corpus and replay a partly-worked night shift over it."""
    if reset:
        db.reset()

    shift = audit_mod.start_shift(
        NIGHT, "Duty controller (night)",
        note="Night shift opened. Southerly storm, warning in force until 06:00.")

    loaded = []
    errors = []
    for adapter_id, payload in _corpus():
        try:
            reporting = to_reporting(payload, adapter_id)
            engine.ingest(reporting, actor=adapter_id, use_llm=use_llm)
            loaded.append(reporting)
        except Exception as exc:  # keep seeding even if one row is malformed
            errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")

    # ---- replay the night shift's work ------------------------------------
    #
    # Deliberately incomplete. The gaps are the demo.

    car = _find(loaded, "car stuck in the water")
    if car:
        car = audit_mod.acknowledge(car, NIGHT)
        audit_mod.add_note(car, "Passed to FENZ by phone as well as forwarding. "
                                "Awaiting confirmation they have a crew on it.", NIGHT)
        forward.forward(car, "fenz", NIGHT,
                        "Person possibly still in the vehicle. Water to door height.")

    gas = _find(loaded, "smell of gas")
    if gas:
        gas = audit_mod.acknowledge(gas, NIGHT)
        forward.forward(gas, "fenz", NIGHT,
                        "Gas smell plus unstable facade with scaffolding. "
                        "Cordon may be needed.")
        audit_mod.add_note(gas, "Also told roading in case Cuba St needs closing.",
                           NIGHT)

    slip = _find(loaded, "slip has come down across ngaio gorge")
    if slip:
        slip = audit_mod.acknowledge(slip, NIGHT)
        audit_mod.set_status(slip, Status.verified, NIGHT,
                             "Confirmed by WCC Roading crew on site — see the "
                             "partner agency update in the same group.")
        forward.forward(slip, "wcc_roads", NIGHT,
                        "Road closed. Geotech assessment requested.")

    # A human disagreeing with the machine, with a reason recorded.
    hub = _find(loaded, "kilbirnie hub")
    if hub:
        hub = audit_mod.acknowledge(hub, NIGHT)
        audit_mod.set_priority(
            hub, Priority.verification_required, NIGHT,
            "Two people asking about medication — needs a welfare callback "
            "tonight, not just awareness.")

    # The rumour: assessed false, and the assessment propagates to the cluster.
    rumour = _find(loaded, "tsunami warning for wellington")
    if rumour:
        rumour = audit_mod.acknowledge(rumour, NIGHT)
        audit_mod.mark_false(
            rumour, NIGHT,
            "Checked against the National Emergency Management Agency feed at "
            "21:40 — no tsunami warning or advisory in force for Wellington. "
            "This is circulating from an unofficial page.")

    sea = _find(loaded, "waves coming right over the sea wall")
    if sea:
        sea = audit_mod.acknowledge(sea, NIGHT)
        audit_mod.set_status(sea, Status.in_review, NIGHT,
                             "Corroborated by the Capital Times item. Asking "
                             "roading whether the lane closure is already in place.")

    flood = _find(loaded, "water is coming up over the footpath")
    if flood:
        flood = audit_mod.acknowledge(flood, NIGHT)
        audit_mod.assign(flood, "welfare.team", NIGHT,
                         "Elderly couple in the ground floor flat — needs a "
                         "doorknock, not just a sandbag.")

    # NOTE: the Island Bay oxygen call and the Petone water call are left
    # untouched on purpose. Neither has been acknowledged by anyone, and both
    # are exactly what the handover briefing must put in front of the next
    # controller.

    # The third rumour post arrives AFTER the false assessment, so it lands
    # pre-flagged rather than climbing the queue again.
    late = to_reporting({
        "post_id": "sm-88530", "platform": "x",
        "url": "https://example.invalid/post/88530",
        "posted_at": _t(4),
        "text": "Is the tsunami warning for Wellington harbour still on? People "
                "are still saying get to high ground",
        "author": {"handle": "@late_poster", "display_name": "Late Poster",
                   "verified": False, "is_official": False,
                   "follower_count": 55, "account_age_days": 30},
        "geo": {"place_name": "Wellington Harbour", "source": "text_inference"},
        "credibility": 0.1, "language": "en",
    }, "social_media")
    engine.ingest(late, actor="social_media", use_llm=use_llm)
    loaded.append(late)

    from . import obligations as _obligations
    try:
        _obligations.save(_demo_timetable())
    except Exception as exc:            # never let the timetable break a seed
        errors.append(f"obligations: {type(exc).__name__}: {exc}")

    stats = {
        "scenario": scenario,
        "loaded": len(loaded),
        "errors": errors,
        "shift": shift.model_dump(mode="json"),
        "by_priority": db.counts_by_priority(),
        "by_status": db.counts_by_status(),
        "unacknowledged": sum(1 for r in db.all_reportings()
                              if not r.acknowledged_by
                              and r.status != Status.false_reporting),
        "note": ("Night shift left open on purpose. Generate the handover "
                 "briefing to see what the outgoing controller never got to."),
    }
    return stats
