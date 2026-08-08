"""Due times — when a thing has to be dealt with by.

Two kinds of row in the queue carry one:

* **Obligations** are due at a time by definition; the timetable states it.
* **Reportings** sometimes imply one. "Expecting a tsunami in 3 hours" is not
  urgent at the moment it arrives and is very urgent two hours and fifty
  minutes later. Nothing else in the triage captures that — priority is about
  what the reporting *is*, not about a clock running down on it.

So a reporting's due time is `received_at + the interval it mentions`, and the
row climbs the queue as that time approaches. An operator can also set one by
hand from the dropdown, which always wins over anything extracted.

The extraction is deliberately conservative. It reads explicit relative
intervals ("in 3 hours", "within 45 minutes", "over the next two hours") and
nothing else. A due time that is wrong is worse than no due time, because it
moves a row for a reason nobody can see — so anything ambiguous is left alone
and the operator can set it themselves. Everything extracted records the phrase
it came from, and the UI shows that phrase.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

# Shared urgency bands. Obligations and reportings classify identically; they
# differ only in how much the band is worth in the queue, which is each
# caller's business.
BANDS = (
    ("overdue", None),
    ("due_now", 15),
    ("soon", 60),
    ("approaching", 120),
    ("upcoming", 240),
    ("later", None),
)

BAND_LABEL = {
    "overdue": "Overdue", "due_now": "Due now", "soon": "Due soon",
    "approaching": "Approaching", "upcoming": "Upcoming", "later": "Later",
    "done": "Done", "none": "—",
}


def band(minutes_until: float | None) -> str:
    if minutes_until is None:
        return "none"
    if minutes_until < 0:
        return "overdue"
    for key, limit in BANDS:
        if limit is not None and minutes_until <= limit:
            return key
    return "later"


def countdown(minutes: float | None) -> str:
    if minutes is None:
        return ""
    late = minutes < 0
    m = int(abs(minutes))
    if m < 60:
        text = f"{m} min"
    elif m < 1440:
        text = f"{m // 60}h {m % 60:02d}m"
    else:
        text = f"{m // 1440}d {(m % 1440) // 60}h"
    return f"{text} overdue" if late else f"in {text}"


def minutes_until(due: datetime | None, now: datetime) -> float | None:
    if due is None:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=now.tzinfo)
    return (due - now).total_seconds() / 60


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
    "fortyfive": 45, "sixty": 60, "ninety": 90, "half": 0.5, "couple": 2,
}

UNIT_MINUTES = {
    "min": 1, "mins": 1, "minute": 1, "minutes": 1,
    "hr": 60, "hrs": 60, "hour": 60, "hours": 60,
    "day": 1440, "days": 1440,
}

_NUM = r"(?:\d+(?:\.\d+)?|" + "|".join(sorted(WORD_NUMBERS, key=len, reverse=True)) + r")"
_UNIT = r"(?:" + "|".join(sorted(UNIT_MINUTES, key=len, reverse=True)) + r")"

# "in 3 hours", "within 45 minutes", "in about two hours", "in half an hour",
# "over the next 2 hours", "expected in ~90 minutes"
_PATTERNS = (
    re.compile(
        rf"\b(?:in|within|inside|after)\s+(?:the\s+)?(?:next\s+)?"
        rf"(?:about|approx\.?|approximately|around|roughly|~)?\s*"
        rf"(?P<num>{_NUM})\s*(?:of\s+)?(?:an?\s+)?(?P<unit>{_UNIT})\b",
        re.IGNORECASE),
    # "over the next 2 hours" is a forecast window. "for the next 2 hours" and
    # "for the next 2 days" are durations of something already happening —
    # a road being shut, crews being on site — and are not deadlines, so
    # `for` and `during` are deliberately excluded.
    re.compile(
        rf"\bover\s+the\s+next\s+"
        rf"(?P<num>{_NUM})\s*(?P<unit>{_UNIT})\b", re.IGNORECASE),
)

# Phrases that mean "already happening", not "due later". Without this,
# "flooding within the last hour" would schedule something an hour out.
_PAST = re.compile(
    r"\b(?:ago|last|past|earlier|since|has been|have been|been going)\b",
    re.IGNORECASE)

# An interval this long is almost never a due time in an EOC queue — it is
# someone describing a forecast window or a road being shut for a week.
MAX_MINUTES = 3 * 1440


def _to_number(token: str) -> float | None:
    token = token.strip().lower()
    if token in WORD_NUMBERS:
        return WORD_NUMBERS[token]
    try:
        return float(token)
    except ValueError:
        return None


def parse_interval(text: str | None) -> tuple[int, str] | None:
    """Find an explicit relative interval. Returns (minutes, matched phrase)."""
    if not text:
        return None
    for pattern in _PATTERNS:
        for m in pattern.finditer(text):
            phrase = m.group(0).strip()
            # Skip anything sitting in a past-tense clause.
            window = text[max(0, m.start() - 40):m.end() + 20]
            if _PAST.search(window):
                continue
            number = _to_number(m.group("num"))
            unit = UNIT_MINUTES.get(m.group("unit").lower())
            if number is None or unit is None:
                continue
            minutes = int(round(number * unit))
            if minutes <= 0 or minutes > MAX_MINUTES:
                continue
            return minutes, phrase
    return None


def extract(text: str | None, received_at: datetime) -> tuple[datetime, str, int] | None:
    """Due time implied by the text. Returns (due_at, phrase, minutes)."""
    found = parse_interval(text)
    if not found:
        return None
    minutes, phrase = found
    return received_at + timedelta(minutes=minutes), phrase, minutes


# ---------------------------------------------------------------------------
# operator dropdown
# ---------------------------------------------------------------------------

# What the operator can pick. Kept short — this is a triage screen, not a
# calendar. `null` clears the due time.
PRESETS = [
    {"minutes": 15, "label": "In 15 minutes"},
    {"minutes": 30, "label": "In 30 minutes"},
    {"minutes": 60, "label": "In 1 hour"},
    {"minutes": 120, "label": "In 2 hours"},
    {"minutes": 180, "label": "In 3 hours"},
    {"minutes": 360, "label": "In 6 hours"},
    {"minutes": 720, "label": "In 12 hours"},
    {"minutes": 1440, "label": "In 24 hours"},
]
