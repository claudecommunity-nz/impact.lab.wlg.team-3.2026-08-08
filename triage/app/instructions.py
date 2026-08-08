"""Operator triage instructions — `config/instructions.md`.

A plain Markdown file the duty controller writes (or uploads) describing how
*this* event should be triaged: what counts as urgent tonight, which areas are
already known, what to hold back. It is handed to the model verbatim on every
classification.

This replaces generating a YAML ruleset from a hazard declaration. The YAML
rules in `triage_rules.yaml` still run and still produce the explainable score —
this is the human's own guidance layered on top, in the form they would write it
for a colleague coming on shift, rather than a format they have to learn.

Two deliberate limits:

* The instructions steer the model, they do not override the guard rails. The
  rules engine still caps social media at verification-required and still holds
  back clusters a controller marked false, whatever the Markdown says.
* Empty is a valid state. With no instructions file the system behaves exactly
  as it did before — this is additive.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import CONFIG_DIR

PATH = CONFIG_DIR / "instructions.md"

MAX_CHARS = 20000

TEMPLATE = """# Triage instructions

<!-- Written by the duty controller. Handed to the model on every reporting.
     The YAML rules still run underneath; this is your guidance on top. -->

## This event

Describe the event: hazard, area, what has already happened.

## Response timeline

e.g. Crews are tasked in 2-hour blocks. Anything I cannot action within
6 hours goes to the morning plan.

## Treat as action required

- ...

## Treat as verification required

- ...

## Already known — do not escalate

- ...
"""


def exists() -> bool:
    return PATH.exists() and bool(PATH.read_text().strip())


def read() -> str:
    return PATH.read_text() if PATH.exists() else ""


def write(text: str, actor: str = "unknown") -> dict:
    if len(text) > MAX_CHARS:
        raise ValueError(
            f"instructions are {len(text)} characters; the limit is {MAX_CHARS}. "
            "Trim them — long instructions crowd out the reporting itself.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(text)
    return info()


def clear() -> None:
    if PATH.exists():
        PATH.unlink()


def info() -> dict:
    if not PATH.exists():
        return {"present": False, "chars": 0, "updated_at": None,
                "path": f"config/{PATH.name}", "template": TEMPLATE}
    stat = PATH.stat()
    text = PATH.read_text()
    return {
        "present": bool(text.strip()),
        "chars": len(text),
        "lines": len(text.splitlines()),
        "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "path": f"config/{PATH.name}",
        "text": text,
        "template": TEMPLATE,
    }


def as_prompt_section() -> str:
    """The block injected into the classifier's system prompt."""
    text = read().strip()
    if not text:
        return ""
    return (
        "\n\n--- CONTROLLER'S INSTRUCTIONS FOR THIS EVENT ---\n"
        "The duty controller wrote the following. Follow it where it applies.\n"
        "It does not override the three rules above about unverified sources, "
        "inventing detail, or vagueness.\n\n"
        f"{text}\n"
        "--- END OF CONTROLLER'S INSTRUCTIONS ---"
    )
