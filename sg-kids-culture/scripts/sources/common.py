import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

import dateutil.parser
import pytz
from bs4 import BeautifulSoup

SG_TZ = pytz.timezone("Asia/Singapore")

@dataclass
class Event:
    title: str
    url: str
    source: str
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    venue: Optional[str] = None
    price: Optional[str] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    categories: Optional[List[str]] = None
    image: Optional[str] = None
    raw_date: Optional[str] = None

    def to_dict(self):
        data = asdict(self)
        if self.start:
            data["start"] = self.start.astimezone(SG_TZ).isoformat()
        if self.end:
            data["end"] = self.end.astimezone(SG_TZ).isoformat()
        return data

def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        return dateutil.parser.parse(text, dayfirst=False, fuzzy=True)
    except (ValueError, OverflowError):
        return None


def parse_age_range(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    patterns = [
        r"ages?\s*(\d{1,2})\s*[–-]\s*(\d{1,2})",
        r"(\d{1,2})\s*to\s*(\d{1,2})\s*years",
        r"(\d{1,2})\+",
        r"for\s*children\s*aged?\s*(\d{1,2})\s*and\s*above",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            if len(m.groups()) == 2:
                return int(m.group(1)), int(m.group(2))
            if len(m.groups()) == 1:
                return int(m.group(1)), None
    return None, None


def extract_jsonld_events(html: str, source: str) -> List[Event]:
    soup = BeautifulSoup(html, "lxml")
    events: List[Event] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") not in ("Event", ["Event"], "MusicEvent", "TheaterEvent"):
                continue
            title = item.get("name") or "Untitled"
            url = item.get("url") or item.get("@id") or ""
            start = parse_date(item.get("startDate"))
            end = parse_date(item.get("endDate"))
            offers = item.get("offers") or {}
            price = None
            if isinstance(offers, dict):
                price = offers.get("priceCurrency", "") + " " + str(offers.get("price")) if offers.get("price") else offers.get("description")
            image = item.get("image")
            venue = None
            loc = item.get("location")
            if isinstance(loc, dict):
                venue = loc.get("name")
            age_min, age_max = parse_age_range(json.dumps(item))
            events.append(Event(
                title=normalize_space(title),
                url=url,
                source=source,
                start=start,
                end=end,
                venue=venue,
                price=price,
                age_min=age_min,
                age_max=age_max,
                image=image,
            ))
    return events


def dedupe(events: List[Event]) -> List[Event]:
    seen = set()
    unique = []
    for ev in events:
        key = (ev.title.lower(), ev.start.isoformat() if ev.start else ev.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ev)
    return unique


def sort_events(events: List[Event]) -> List[Event]:
    return sorted(events, key=lambda e: e.start or datetime.now(tz=SG_TZ))
