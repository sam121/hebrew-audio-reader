import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from urllib.parse import urlparse
from typing import List, Optional

import dateutil.parser
import pytz
from bs4 import BeautifulSoup

SG_TZ = pytz.timezone("Asia/Singapore")

BLOCKED_TITLE_TERMS = {
    "exhibitions",
    "programmes",
    "plan your itinerary",
    "admissions",
    "museum map",
    "accessibility at the museum",
    "for groups",
    "shop & dine",
    "online exhibitions",
    "about us",
    "view all",
    "festivals & series",
    "festivals",
    "series",
    "free programmes",
    "collaborations",
    "playtime!",
    "whats on",
    "what's on",
}

BLOCKED_URL_TERMS = [
    "/plan-your-visit/",
    "/about-us/",
    "/shop-and-dine/",
    "/virtual-gallery/",
    "/visitor-information/",
    "/museum-map",
    "/view-all",
    "/whats-on/overview",
]

BLOCKED_URL_PATHS = {
    "/whats-on/festivals-and-series",
    "/whats-on/festivals-and-series/festivals",
    "/whats-on/festivals-and-series/series",
    "/whats-on/festivals-and-series/free-programmes",
    "/whats-on/festivals-and-series/collaborations",
    "/whats-on/festivals-and-series/series/playtime",
    "/whats-on/sg-culture-pass",
}

CATEGORY_ORDER = [
    "Theatre",
    "Opera",
    "Orchestra",
    "Cinema",
    "Dance",
    "Music",
    "Workshop",
    "Exhibition",
]

CATEGORY_PATTERNS = {
    "Theatre": re.compile(r"\b(theatre|theater|playtime|play\b|musical|drama|puppet|stage)\b", re.IGNORECASE),
    "Opera": re.compile(r"\bopera\b", re.IGNORECASE),
    "Orchestra": re.compile(r"\b(orchestra|symphony|philharmonic)\b", re.IGNORECASE),
    "Cinema": re.compile(r"\b(cinema|film|movie|screening)\b", re.IGNORECASE),
    "Dance": re.compile(r"\b(dance|ballet|choreograph|hip[\s-]?hop)\b", re.IGNORECASE),
    "Music": re.compile(r"\b(music|concert|choir|jazz|recital|ensemble|band|organ)\b", re.IGNORECASE),
    "Workshop": re.compile(r"\b(workshop|masterclass|class|lab|hands[\s-]?on)\b", re.IGNORECASE),
    "Exhibition": re.compile(r"\b(exhibition|exhibit|gallery|museum|installation|visual[\s-]?arts)\b", re.IGNORECASE),
}

SOURCE_DEFAULT_CATEGORIES = {
    "sso": ["Orchestra", "Music"],
    "sco": ["Orchestra", "Music"],
    "wildrice": ["Theatre"],
    "srt": ["Theatre"],
    "practice": ["Theatre", "Music"],
    "gallery": ["Exhibition"],
    "nhb": ["Exhibition"],
    "acm": ["Exhibition"],
    "sam": ["Exhibition"],
    "artscience": ["Exhibition"],
    "sandstheatre": ["Theatre", "Music"],
    "peranakan": ["Exhibition"],
    "ihc": ["Exhibition"],
    "childrensmuseum": ["Exhibition"],
    "changi": ["Exhibition"],
    "bukitchandu": ["Exhibition"],
    "sccc": ["Music", "Workshop"],
    "gateway": ["Theatre"],
}

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
    age_ranges: Optional[List[tuple[Optional[int], Optional[int]]]] = None
    categories: Optional[List[str]] = None
    image: Optional[str] = None
    raw_date: Optional[str] = None

    def to_dict(self):
        data = asdict(self)
        if self.start:
            data["start"] = self.start.astimezone(SG_TZ).isoformat()
        if self.end:
            data["end"] = self.end.astimezone(SG_TZ).isoformat()
        if self.raw_date:
            data["raw_date"] = clean_text(self.raw_date)
        return data

def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def clean_text(text: str) -> str:
    # Strip embedded markup/scripts from extracted text blobs before serializing.
    plain = BeautifulSoup(text, "lxml").get_text(" ", strip=True)
    return normalize_space(plain)


def parse_date(text: str) -> Optional[datetime]:
    if not text:
        return None
    try:
        normalized = clean_text(text)
        normalized = re.sub(r"\s*/\s*", " ", normalized)
        normalized = re.sub(
            r"(\d{1,2})\.(\d{2})\s*(am|pm)\b",
            lambda m: f"{m.group(1)}:{m.group(2)} {m.group(3)}",
            normalized,
            flags=re.IGNORECASE,
        )
        dt = dateutil.parser.parse(normalized, dayfirst=False, fuzzy=True)
        if dt.tzinfo is None:
            dt = SG_TZ.localize(dt)
        else:
            dt = dt.astimezone(SG_TZ)
        now = datetime.now(tz=SG_TZ)
        if dt.year < now.year - 1 or dt.year > now.year + 3:
            return None
        return dt
    except (ValueError, OverflowError):
        return None


def _normalize_age_range(lo: Optional[int], hi: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    if lo is not None and lo > 17:
        return None, None
    if hi is not None:
        if hi < 0:
            return None, None
        hi = min(hi, 17)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _to_years(value: int, unit: str, round_up: bool = False) -> int:
    unit_l = (unit or "year").lower()
    if unit_l.startswith("month"):
        if round_up:
            return max(0, (value + 11) // 12)
        return max(0, value // 12)
    return max(0, value)


def parse_age_ranges(text: str) -> List[tuple[Optional[int], Optional[int]]]:
    if not text:
        return []
    text_blob = clean_text(text).lower()
    if not text_blob:
        return []

    candidates: List[tuple[Optional[int], Optional[int], int]] = []
    patterns = [
        # Highest confidence: explicit unit-based recommended ages (months/years).
        (4, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(months?|years?)\s*(?:to|[–-])\s*(\d{1,2})\s*(months?|years?)", "range_with_unit"),
        (4, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(months?|years?)\s*(?:\+|and\s*above)", "plus_with_unit"),
        (4, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(?:to|[–-])\s*(\d{1,2})\s*(months?|years?)", "range_with_trailing_unit"),
        (4, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(?:\+|and\s*above)\s*(months?|years?)", "plus_with_trailing_unit"),
        # Highest confidence: explicit recommended-age labels.
        (3, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(?:to|[–-])\s*(\d{1,2})", "range"),
        (3, r"recommended\s*age(?:s)?\s*[:\-]?\s*(\d{1,2})\s*(?:\+|and\s*above)", "plus"),
        # Medium confidence: suitable-for / ages labels.
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(months?|years?)\s*(?:to|[–-])\s*(\d{1,2})\s*(months?|years?)", "range_with_unit"),
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(months?|years?)\s*(?:\+|and\s*above)", "plus_with_unit"),
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(?:to|[–-])\s*(\d{1,2})\s*(months?|years?)", "range_with_trailing_unit"),
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(?:\+|and\s*above)\s*(months?|years?)", "plus_with_trailing_unit"),
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(?:to|[–-])\s*(\d{1,2})(?:\s*years?(?:\s*old)?)?", "range"),
        (2, r"(?:suitable\s*for|for\s*children\s*aged?|ages?)\s*[:\-]?\s*(\d{1,2})\s*(?:\+|and\s*above)", "plus"),
        # Lower confidence: unlabeled age statements.
        (1, r"\b(\d{1,2})\s*(?:to|[–-])\s*(\d{1,2})\s*years?(?:\s*old)?\b", "range"),
        (1, r"\b(\d{1,2})\s*(?:\+|and\s*above)\s*years?(?:\s*old)?\b", "plus"),
    ]

    for priority, pattern, kind in patterns:
        for match in re.finditer(pattern, text_blob, flags=re.IGNORECASE):
            if kind == "range":
                lo, hi = int(match.group(1)), int(match.group(2))
            elif kind == "plus":
                lo, hi = int(match.group(1)), None
            elif kind == "range_with_unit":
                lo_val, lo_unit = int(match.group(1)), match.group(2)
                hi_val, hi_unit = int(match.group(3)), match.group(4)
                lo = _to_years(lo_val, lo_unit, round_up=False)
                hi = _to_years(hi_val, hi_unit, round_up=True)
            elif kind == "plus_with_unit":
                lo_val, lo_unit = int(match.group(1)), match.group(2)
                lo, hi = _to_years(lo_val, lo_unit, round_up=False), None
            elif kind == "range_with_trailing_unit":
                lo_val, hi_val = int(match.group(1)), int(match.group(2))
                unit = match.group(3)
                lo = _to_years(lo_val, unit, round_up=False)
                hi = _to_years(hi_val, unit, round_up=True)
            elif kind == "plus_with_trailing_unit":
                lo_val, unit = int(match.group(1)), match.group(2)
                lo, hi = _to_years(lo_val, unit, round_up=False), None
            else:
                continue
            lo, hi = _normalize_age_range(lo, hi)
            if lo is None and hi is None:
                continue
            candidates.append((lo, hi, priority))

    if not candidates:
        return []

    max_priority = max(p for _, _, p in candidates)
    picked = [(lo, hi) for lo, hi, p in candidates if p == max_priority]
    # Deduplicate while preserving order.
    seen = set()
    out: List[tuple[Optional[int], Optional[int]]] = []
    for lo, hi in picked:
        key = (lo, hi)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def parse_age_range(text: str) -> tuple[Optional[int], Optional[int]]:
    ranges = parse_age_ranges(text)
    return summarize_age_ranges(ranges)


def parse_date_range(text: str) -> tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    if not text:
        return None, None, None
    blob = clean_text(text)
    patterns = [
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\s*(?:to|[–-])\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2})\s*(?:to|[–-])\s*(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, blob, flags=re.IGNORECASE):
            start = parse_date(match.group(1))
            end = parse_date(match.group(2))
            if not start or not end:
                continue
            if end < start:
                continue
            return start, end, match.group(0)
    return None, None, None


def summarize_age_ranges(
    ranges: List[tuple[Optional[int], Optional[int]]],
) -> tuple[Optional[int], Optional[int]]:
    if not ranges:
        return None, None
    mins = [lo for lo, _ in ranges if lo is not None]
    maxes = [hi for _, hi in ranges if hi is not None]
    age_min = min(mins) if mins else None
    age_max = None if any(hi is None for _, hi in ranges) else (max(maxes) if maxes else None)
    return age_min, age_max


def age_bucket(age_min: Optional[int], age_max: Optional[int]) -> str:
    if age_max is not None:
        if age_max <= 5:
            return "0-5"
        if age_max <= 12:
            return "6-12"
    if age_min is None:
        return "all"
    if age_min <= 5:
        return "0-5"
    if age_min <= 12:
        return "6-12"
    if age_min <= 17:
        return "13-17"
    return "all"


def infer_categories(
    title: str,
    url: str,
    source: str,
    text_blob: str = "",
    jsonld_type: Optional[str] = None,
) -> List[str]:
    hits: list[str] = []

    def add(category: str):
        if category in CATEGORY_ORDER and category not in hits:
            hits.append(category)

    src = (source or "").lower()
    for category in SOURCE_DEFAULT_CATEGORIES.get(src, []):
        add(category)

    event_type = (jsonld_type or "").lower()
    if event_type == "musicevent":
        add("Music")
    if event_type == "theaterevent":
        add("Theatre")

    haystack = " ".join([title or "", url or "", text_blob or ""])
    for category in CATEGORY_ORDER:
        pattern = CATEGORY_PATTERNS[category]
        if pattern.search(haystack):
            add(category)
    return hits


def is_probable_event(event: Event) -> bool:
    title = normalize_space(event.title).lower()
    if not title:
        return False
    if title in BLOCKED_TITLE_TERMS:
        return False
    url = (event.url or "").strip()
    if not url.startswith("http"):
        return False
    parsed = urlparse(url)
    path = parsed.path.lower()
    path = path.rstrip("/") or "/"
    if any(term in path for term in BLOCKED_URL_TERMS):
        return False
    if path in BLOCKED_URL_PATHS:
        return False
    if path.endswith(("/about", "/contact", "/sponsors")):
        return False
    if "/festivals-and-series/" in path and path.endswith("/events"):
        return False
    if "category=" in (parsed.query or "").lower():
        return False
    event_path_hints = (
        "/whats-on/",
        "/events/",
        "/event/",
        "/concert",
        "/programme",
        "/programmes",
        "/performance",
        "/festival",
        "/exhibition",
        "/show",
    )
    if not any(hint in path for hint in event_path_hints):
        return False
    # Must have at least one hint of timing or age relevance.
    if not event.start and event.age_min is None and event.age_max is None:
        return False
    return True


def is_upcoming_event(event: Event, reference: Optional[datetime] = None) -> bool:
    ref = reference or datetime.now(tz=SG_TZ)
    ref_date = ref.astimezone(SG_TZ).date()
    if event.end:
        return event.end.astimezone(SG_TZ).date() >= ref_date
    if event.start:
        return event.start.astimezone(SG_TZ).date() >= ref_date
    # Keep undated events; caller may choose to hide separately.
    return True


def extract_jsonld_events(
    html: str,
    source: str,
    page_url: Optional[str] = None,
    fallback_age_text: Optional[str] = None,
) -> List[Event]:
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
            item_type = item.get("@type")
            if item_type not in ("Event", ["Event"], "MusicEvent", "TheaterEvent"):
                continue
            title = item.get("name") or "Untitled"
            url = item.get("url") or item.get("@id") or page_url or ""
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
            age_ranges = parse_age_ranges(json.dumps(item))
            if not age_ranges and fallback_age_text:
                age_ranges = parse_age_ranges(fallback_age_text)
            age_min, age_max = summarize_age_ranges(age_ranges)
            categories = infer_categories(
                title=title,
                url=url,
                source=source,
                text_blob=json.dumps(item),
                jsonld_type=(item_type[0] if isinstance(item_type, list) and item_type else item_type),
            )
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
                age_ranges=age_ranges or None,
                categories=categories or None,
                image=image,
            ))
    return events


def dedupe(events: List[Event]) -> List[Event]:
    def merge_events(left: Event, right: Event) -> Event:
        merged = left
        if not merged.start or (right.start and right.start < merged.start):
            merged.start = right.start or merged.start
        if not merged.end or (right.end and right.end > merged.end):
            merged.end = right.end or merged.end
        if not merged.venue:
            merged.venue = right.venue
        if not merged.price:
            merged.price = right.price
        if merged.age_min is None:
            merged.age_min = right.age_min
        if merged.age_max is None:
            merged.age_max = right.age_max
        if right.age_ranges:
            existing = set(tuple(x) for x in (merged.age_ranges or []))
            combined = list(merged.age_ranges or [])
            for rng in right.age_ranges:
                key = tuple(rng)
                if key not in existing:
                    existing.add(key)
                    combined.append(rng)
            merged.age_ranges = combined
        if not merged.image:
            merged.image = right.image
        if not merged.raw_date:
            merged.raw_date = right.raw_date
        if right.categories:
            existing = set(merged.categories or [])
            combined = list(merged.categories or [])
            for category in right.categories:
                if category not in existing:
                    existing.add(category)
                    combined.append(category)
            merged.categories = combined
        return merged

    by_key: dict[tuple[str, str], Event] = {}
    for ev in events:
        if ev.url:
            key = ("url", ev.url.rstrip("/").lower())
        else:
            start_key = ev.start.isoformat() if ev.start else ""
            key = ("title_start", f"{ev.title.lower()}|{start_key}")
        if key in by_key:
            by_key[key] = merge_events(by_key[key], ev)
            continue
        by_key[key] = ev
    return list(by_key.values())


def sort_events(events: List[Event]) -> List[Event]:
    fallback = datetime.now(tz=SG_TZ)
    return sorted(events, key=lambda e: e.start.astimezone(SG_TZ) if e.start else fallback)
