"""How each channel sounds.

If every report reads the same, the demo dies. A 3am phone call is fragmentary
and frightened and was typed by someone listening to it, not by the caller. A
social post is short, lowercase and badly punctuated. A form submission has been
squeezed through labelled boxes. A partner agency email is formal and structured
and arrives an hour after the thing it describes.

The same incident worded six different ways is what makes grouping worth doing.
So the banks below are organised by channel first and issue second: picking a
different template for each member of a duplicate cluster gives reports that
share a meaning and share almost no words.

Nothing in here names a person, a house number on an evacuated street, or a
phone number. Streets and suburbs only.
"""

from __future__ import annotations

# ---------------------------------------------------------------- phone
# Call-taker notes. Fragmentary, abbreviated, written while someone talks.
PHONE = {
    "flooding": [
        "caller reports water over the road at {place} - says it's rising fast",
        "water coming into the house at {place}, caller very distressed, kids in the property",
        "{place} - caller says whole street is underwater, cars floating",
        "female caller {place}, water through the garage and coming up the hall",
        "caller can't get out of driveway {place}, water up to the wheel arches",
        "{place} - water over the footpath, caller asking if she should leave",
        "male caller, {place}, says drains have given up and it's coming in the back door",
        "caller reports flooding {place} - was ankle deep an hour ago, now knee deep",
        "{place}, caller says water is up over the front step and still coming",
        "call dropped out - {place}, flooding, sounded like water in the house",
    ],
    "slip": [
        "caller reports slip across the road at {place}, no way through",
        "{place} - bank has come down, caller says it's still moving",
        "slip at {place}. caller says mud and trees across both lanes",
        "{place} - caller heard a bang, hillside has come away behind the houses",
        "caller says the ground has moved above {place}, cracks in the driveway",
        "{place}, slip onto the road, caller thinks a car may be under it - unconfirmed",
    ],
    "road": [
        "{place} impassable, caller turned around, water too deep",
        "caller reports road closed at {place} but no cones or signage",
        "{place} - caller stuck, can't go forward or back",
        "road under water {place}, caller asking for an alternative route",
        "caller reports debris across {place}, hit something in the dark",
    ],
    "power": [
        "caller reports power out at {place}, whole street dark",
        "{place} - no power since about an hour ago, caller on oxygen concentrator",
        "power off {place}, caller says she heard a bang and saw a flash",
        "{place} - lines down across the road, caller keeping people back",
    ],
    "water": [
        "caller reports water coming up through the road at {place}, thinks it's a main",
        "{place} - no water at the tap since this morning",
        "brown water out of the taps {place}, caller asking if it's safe",
        "{place}, caller says there's a fountain coming out of the footpath",
    ],
    "tree": [
        "tree down across {place}, blocking the road",
        "{place} - large branch on the powerlines, caller worried it'll come down",
        "caller reports tree on a car at {place}, no one in it",
    ],
    "evacuation": [
        "caller says they've been told to leave their house at {place}",
        "{place} - caller and neighbours getting out, water rising fast, asking where to go",
        "caller at {place} refusing to leave, wants to know if it's compulsory",
        "{place}, caller says emergency services are door knocking the street",
        "caller evacuating {place} with two elderly neighbours, asking about the centre",
    ],
    "rumour": [
        "caller asking if it's true that {place} has been evacuated - heard it from a neighbour",
        "caller wants to confirm something she saw online about {place}",
        "{place} - caller says her son messaged that the river's over the banks there. not first hand",
        "caller heard on the radio that {place} is cut off, asking if that's right",
    ],
    "vague": [
        "caller reports flooding at the bottom of the valley, wouldn't give an address",
        "caller says the road's blocked past the roundabout, big slip. no street name",
        "water everywhere down our street - caller couldn't say which street, line poor",
        "caller reports something come down across the road up the hill. no further detail",
        "elderly caller, very distressed, water in the house, address not obtained before the line dropped",
        "caller says it's flooding near the school. didn't say which school",
    ],
}

# ---------------------------------------------------------------- social
# Short, lowercase, poorly punctuated, often second-hand.
SOCIAL = {
    "flooding": [
        "{place} is a river right now. never seen it like this",
        "anyone else in {place}? water is up over the kerb and still rising",
        "well {place} is officially underwater",
        "our street in {place} is gone. water halfway up the front lawn",
        "do not drive through {place} it is deeper than it looks",
        "{place} flooding again. third time this year and nothing gets done",
        "water coming up through the drains at {place}, this is not good",
        "just waded down {place} to check on mum. knee deep",
    ],
    "slip": [
        "big slip at {place}, road completely blocked",
        "{place} - whole bank has come down. dont go that way",
        "theres a slip across {place}, saw it on the way home",
        "hillside has let go above {place}. looks bad",
    ],
    "road": [
        "avoid {place}, its closed",
        "{place} shut both ways, no idea how long",
        "took me an hour to get past {place} tonight",
        "is {place} open? cant get through the usual way",
    ],
    "power": [
        "power out in {place}, anyone else?",
        "no power {place} for about 2 hours now",
        "{place} in the dark. lines company website says nothing",
    ],
    "water": [
        "anyone in {place} got water? ours is brown",
        "theres water bubbling up out of the road at {place}",
        "no water at all in {place} since this morning",
    ],
    "tree": [
        "massive tree down at {place}",
        "tree across the road {place}, squeezed past on the footpath",
    ],
    "evacuation": [
        "they're evacuating {place}. absolute chaos",
        "friends just got told to leave their place on {place}",
        "{place} being evacuated apparently. stay safe everyone",
    ],
    "rumour": [
        "hearing the whole of {place} is underwater?? can anyone confirm",
        "someone posted that {place} has been evacuated - is that right",
        "word going round the river's broken its banks at {place}. anyone actually there",
        "my cousin says {place} is completely cut off. no idea if thats true",
        "seen a photo going round of {place} but not sure its even from today",
        "is it true about {place}? seen three different things now",
    ],
    "vague": [
        "the whole bottom of the valley is flooded",
        "road past the roundabout is blocked, big slip",
        "cant get out of our street, water everywhere",
        "somethings come down across the road up the hill",
    ],
}

# ---------------------------------------------------------------- form
# Squeezed through labelled boxes on a council web form.
FORM = {
    "flooding": [
        "Surface flooding. {place}. Water across full width of road, approx 300mm deep, rising.",
        "Flooding. {place}. Stormwater not draining, water entering property.",
        "Reporting flooding at {place}. Has been getting worse over the last hour.",
        "{place}. Road flooded and impassable to small vehicles. No signage in place.",
        "Flooding of garage and driveway, {place}. Water coming from the road.",
    ],
    "slip": [
        "Landslide. {place}. Material across carriageway, road blocked.",
        "Slip. {place}. Bank above the road has failed, debris on the footpath.",
        "Reporting a slip at {place}. Appears to still be moving.",
    ],
    "road": [
        "Road blocked. {place}. Unable to pass, no detour signposted.",
        "{place}. Requesting closure - conditions unsafe.",
        "Debris on carriageway, {place}.",
    ],
    "power": [
        "Power outage. {place}. Approximately 2 hours, no estimate given.",
        "Lines down. {place}. Hazard to pedestrians.",
    ],
    "water": [
        "Suspected water main break. {place}. Water surfacing through the road.",
        "No water supply. {place}. Since approximately 09:00.",
        "Discoloured water supply, {place}.",
    ],
    "tree": [
        "Fallen tree. {place}. Across carriageway.",
        "Tree down on powerlines, {place}. Hazard.",
    ],
    "evacuation": [
        "Requesting advice. {place}. Have been told to evacuate, need somewhere to go.",
        "{place}. Evacuated the property at approximately 17:00. Reporting for the record.",
    ],
    "rumour": [
        "Requesting confirmation. Have seen reports that {place} is being evacuated. Cannot verify.",
        "Reporting information seen on social media regarding {place}. Not witnessed personally.",
    ],
    "vague": [
        "Flooding. Location: bottom of the hill by the shops. Water across the road.",
        "Reporting a slip. Location not known exactly, past the roundabout on the main road.",
        "Water through our property. Have not given an address as I am not at home.",
    ],
}

# ---------------------------------------------------------------- email
# Formal, structured, often from a business, school or residents' group.
EMAIL = {
    "flooding": [
        "Good morning. I am writing to report significant surface flooding at {place}. "
        "The water is now across the full width of the road and appears to be rising. "
        "Could someone advise whether the road is to be closed.",
        "To whom it may concern - we have water entering the building at {place}. "
        "Staff have moved stock upstairs. Please advise whether assistance is available.",
        "Reporting flooding at {place}. This has been an ongoing issue at this location "
        "and it is considerably worse this morning than in previous events.",
    ],
    "slip": [
        "Please be advised there is a substantial slip across the road at {place}. "
        "The road is impassable in both directions. We have not seen any contractors on site.",
        "I wish to report a landslip at {place}. There are cracks appearing in the ground "
        "above the affected area and in my view it has not finished moving.",
    ],
    "road": [
        "Advising that {place} is impassable. Several vehicles have turned back. "
        "There is no signage or cordon in place and it is dark.",
        "The access road at {place} is blocked. We have residents who cannot get home.",
    ],
    "power": [
        "Confirming loss of supply at {place}. We hold a list of residents on medical "
        "equipment and would appreciate an estimated restoration time.",
    ],
    "water": [
        "Reporting a suspected main break at {place}. Water has been surfacing through "
        "the carriageway since early this morning.",
    ],
    "tree": [
        "Advising a large tree has come down across {place} and is resting on the lines.",
    ],
    "evacuation": [
        "Writing on behalf of residents at {place}. A number of households have left "
        "their properties this evening. We would like to know where people should go.",
        "Our residents' association has been assisting households evacuating from {place}. "
        "Please advise the location of the assistance centre.",
    ],
    "rumour": [
        "I have seen reports circulating that {place} has been evacuated. I have not been "
        "able to confirm this from any official source and would appreciate clarification.",
    ],
    "vague": [
        "Writing to report flooding in our area. I am reluctant to give the exact address "
        "but the water is across the road and into several properties.",
        "There is a slip somewhere on the main road out of the valley. I did not stop to "
        "look at exactly where.",
    ],
}

# ---------------------------------------------------------------- news
# Headline and lede. These carry a real URL, because these articles exist.
NEWS = [
    "State of emergency declared for the Wellington region after a night of heavy rain, "
    "flooding and slips across the city and the Hutt Valley.",
    "Wellington region under a state of emergency as more rain arrives on top of "
    "overnight flooding and slips.",
    "Emergency services attended close to 200 weather-related callouts across the "
    "Wellington region from 2am, with flooding reported in southern suburbs.",
    "Residents in parts of Wainuiomata have been evacuated as streams overtopped "
    "following overnight rainfall.",
    "An emergency assistance centre has opened at the Wellington City Mission on "
    "Oxford Terrace for people displaced by flooding.",
    "Around ten homes across Berhampore, Mornington and South Karori have been assessed "
    "as uninhabitable following flooding and slips.",
    "More than 130mm of rain fell at Berhampore over the course of Monday, with 77mm of "
    "it in the hour to 3am - three times any other hour in nine months of record.",
    "Wellington City Council is asking people to stay off the roads this evening unless "
    "their journey is essential, with surface flooding and slips across the city.",
    "Civil Defence says the state of emergency gives it powers to evacuate properties "
    "and close roads, and asks residents to follow instructions from emergency services.",
    "Streets in Wainuiomata remain closed this evening after streams overtopped, with "
    "residents of several properties spending the night elsewhere.",
    "The Wellington region's state of emergency remains in place overnight as further "
    "rain is forecast, Civil Defence says.",
]

# ---------------------------------------------------------------- partner
# Pre-structured job records from another agency. The easy case, deliberately a
# minority of the stream. Format mirrors a Wellington Water job entry.
PARTNER_FAULTS = [
    ("Blockage - Significant", "Storm Water", "High"),
    ("Blockage - Significant", "Storm Water", "Urgent"),
    ("General Fault", "Storm Water", "Medium"),
    ("Leaking Pipes", "Potable Water", "Medium"),
    ("Overflow", "Waste Water", "High"),
    ("General Fault", "Waste Water", "Medium"),
]

PARTNER_PREFIX = {
    "fenz": "FENZ incident referral",
    "water": "Wellington Water job",
    "police": "NZ Police referral",
    "lines": "Wellington Electricity job",
}


# ---------------------------------------------------------------- late
# The same incident, reported hours after it happened. Time matters as much as
# place: a report arriving at 9pm about water that came through at 4am is not a
# new incident, and a queue that treats it as one has just invented an event.
LATE = {
    "phone": [
        "caller following up on {place} - says nobody has been out and it's been like this since this morning",
        "caller reporting flooding at {place} from earlier today, only ringing now, phones were down",
        "{place} - caller says the water went through hours ago, wants to know who assesses the damage",
        "caller has been trying to get through all day about {place}",
    ],
    "social": [
        "still nothing done about {place} and this was at 4 this morning",
        "posting this late but {place} was completely underwater earlier",
        "{place} this morning. anyone know if the council has been out yet",
    ],
    "form": [
        "Reporting flooding that occurred at {place} earlier today. Water has since receded.",
        "{place}. Incident occurred approximately 04:00. Reporting now for the record.",
    ],
    "email": [
        "Apologies for the delay in reporting. Water entered several properties at {place} "
        "in the early hours of this morning. We have had no phone or internet since.",
        "Writing to place on record that {place} flooded this morning. I appreciate it is "
        "some hours ago now but I understand you are compiling a picture of the event.",
    ],
}

BANKS = {
    "phone": PHONE,
    "social": SOCIAL,
    "form": FORM,
    "email": EMAIL,
}


def bank(channel: str, issue: str) -> list[str]:
    """Templates for a channel and issue, falling back to flooding.

    Flooding is the fallback because it is the event: on a night like 20 April
    almost everything a channel carries is some flavour of water where it should
    not be.
    """
    templates = BANKS[channel]
    return templates.get(issue) or templates["flooding"]
