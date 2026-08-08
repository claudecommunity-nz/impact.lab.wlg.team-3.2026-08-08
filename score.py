"""Score the current assessor against the answer key.

    python3 score.py

Run it after every change to triage.py. A triage prototype nobody has measured
is just an opinion with a colour scheme.

The corpus has two kinds of report and they must not be scored together:

  32 human-written reports   phone, form, social, email, news. Ground-truthed
                             with a true location and a category. These are
                             the ones the problem statement is about.
  44 partner job records     Real Wellington Water job entries. They arrive
                             pre-structured, so getting them right proves
                             nothing about reading messy human text.

Scoring the whole 76 together flatters the result badly - the job records drag
the average up by about forty points. Only the 32 mean anything.
"""

from __future__ import annotations

import collections
import json
import pathlib

import triage

DATA = pathlib.Path(__file__).parent / "data"
CATEGORIES = ("action", "verify", "awareness")


def load() -> tuple[list[dict], dict]:
    with open(DATA / "reports.json") as fh:
        reports = json.load(fh)["reports"]
    with open(DATA / "answer-key.json") as fh:
        key = {k["id"]: k for k in json.load(fh)["key"]}
    return reports, key


def main() -> None:
    reports, key = load()
    human = [r for r in reports if key.get(r["id"], {}).get("true_place")]
    partner = [r for r in reports if r["id"] in key and r not in human]

    assessed = {r["id"]: triage.assess(r) for r in reports}

    located = sum(
        1 for r in human
        if assessed[r["id"]]["place"]
        and assessed[r["id"]]["place"].lower() in key[r["id"]]["true_place"].lower()
    )
    correct = sum(
        1 for r in human
        if assessed[r["id"]]["category"] == key[r["id"]]["category"]
    )

    predicted_groups = {
        assessed[r["id"]]["incident"] for r in human if assessed[r["id"]]["incident"]
    }
    true_groups = {key[r["id"]]["incident"] for r in human}

    n = len(human)
    print(f"assessor: {triage.ASSESSOR}")
    print(f"scored:   {n} human-written reports "
          f"({len(partner)} partner job records excluded)\n")
    print(f"  location  {located}/{n}  {located / n:.0%}")
    print(f"  category  {correct}/{n}  {correct / n:.0%}")
    print(f"  grouping  {len(predicted_groups)} incidents found, "
          f"{len(true_groups)} true\n")

    matrix = collections.Counter(
        (key[r["id"]]["category"], assessed[r["id"]]["category"]) for r in human
    )
    width = max(len(c) for c in CATEGORIES)
    print("  truth \\ predicted".ljust(width + 4)
          + "".join(c.rjust(width + 2) for c in CATEGORIES))
    for truth in CATEGORIES:
        row = "".join(str(matrix[(truth, p)] or "-").rjust(width + 2)
                      for p in CATEGORIES)
        total = sum(matrix[(truth, p)] for p in CATEGORIES)
        print(f"  {truth.ljust(width + 2)}{row}    ({total} true)")

    misses = [
        (r, key[r["id"]]["category"], assessed[r["id"]])
        for r in human
        if assessed[r["id"]]["category"] != key[r["id"]]["category"]
    ]
    buried = [m for m in misses if m[1] == "action"]
    if buried:
        print(f"\n  {len(buried)} report(s) needing ACTION were not called action.")
        print("  For an emergency tool this is the expensive direction to miss in.\n")
        for report, truth, a in buried[:6]:
            print(f"    {report['id']}  called {a['category']:9} "
                  f"| {report['text'][:62]}")


if __name__ == "__main__":
    main()
