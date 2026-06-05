from __future__ import annotations

import json
from pathlib import Path
from typing import List

from sources import artshouse, cultural_centres, esplanade, gallery, nhb, sco, sso
from sources.common import Event, dedupe, is_probable_event, is_upcoming_event, sort_events

SOURCES = [
    esplanade,
    sso,
    sco,
    artshouse,
    gallery,
    nhb,
    cultural_centres,
]


def run() -> List[Event]:
    events: List[Event] = []
    for module in SOURCES:
        try:
            try:
                events.extend(module.fetch(max_events=80))
            except TypeError:
                events.extend(module.fetch())
        except Exception as exc:  # pragma: no cover
            print(f"[warn] {module.__name__} failed: {exc}")
    events = [e for e in events if is_probable_event(e)]
    events = [e for e in events if is_upcoming_event(e)]
    events = dedupe(events)
    events = sort_events(events)
    return events


def save_events(events: List[Event], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([e.to_dict() for e in events], f, indent=2)


def main():
    events = run()
    save_events(events, Path("data/events.json"))
    print(f"Saved {len(events)} events to data/events.json")


if __name__ == "__main__":
    main()
