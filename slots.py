# The weekly posting slots, read from slots.yaml.

from pathlib import Path

import yaml

SLOTS_FILE = Path(__file__).parent / "slots.yaml"


def load():
    """Every slot in the week, in order."""
    return yaml.safe_load(SLOTS_FILE.read_text())["slots"]


def drafted_here():
    """Every slot the shortlist picks for."""
    return load()


def by_name(name):
    """The slot with this name, or None (for picks made before slots existed)."""
    return next((s for s in load() if s["name"] == name), None)


def label(slot):
    """"Mon · news take", for messages."""
    return f"{slot['day']} · {slot['name']}"


def describe_for_shortlist():
    """The week as the shortlist prompt sees it."""
    lines = []
    for s in load():
        lines.append(f"- {s['day']}, slot name \"{s['name']}\": {s['wants']}")
    return "\n".join(lines)
