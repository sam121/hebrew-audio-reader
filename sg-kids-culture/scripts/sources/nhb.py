from __future__ import annotations

from bs4 import BeautifulSoup

from .common import (
    Event,
    extract_jsonld_events,
    infer_categories,
    normalize_space,
    parse_age_ranges,
    parse_date,
    parse_date_range,
    summarize_age_ranges,
)
from .http import get

NMS_BASE = "https://www.nhb.gov.sg/nationalmuseum"
NMS_LISTING = f"{NMS_BASE}/whats-on"
ACM_BASE = "https://www.nhb.gov.sg/acm"
ACM_LISTING = f"{ACM_BASE}/whats-on/programmes"

BLOCKED_PATH_SNIPPETS = [
    "/whats-on/exhibition/exhibitions",
    "/whats-on/programme/programmes",
    "/whats-on/plan-your-itinerary",
    "/whats-on/view-all",
]


def _collect_links(html: str, base: str, limit: int = 15) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = base + href
        href_l = href.lower()
        if not href_l.startswith(base.lower()):
            continue
        if "/whats-on/" not in href_l:
            continue
        if any(snippet in href_l for snippet in BLOCKED_PATH_SNIPPETS):
            continue
        if href not in links:
            links.append(href)
        if len(links) >= limit:
            break
    return links


def fetch(max_events: int = 25) -> list[Event]:
    events: list[Event] = []

    for base, listing in [(NMS_BASE, NMS_LISTING), (ACM_BASE, ACM_LISTING)]:
        html = get(listing)
        if not html:
            continue
        events.extend(extract_jsonld_events(html, "nhb", page_url=listing))
        links = _collect_links(html, base, limit=max_events)
        for url in links:
            page = get(url)
            if not page:
                continue
            jsonld = extract_jsonld_events(page, "nhb", page_url=url)
            if jsonld:
                events.extend(jsonld)
                continue
            soup_ev = BeautifulSoup(page, "lxml")
            title_el = soup_ev.find("h1")
            start, end, raw_date = parse_date_range(page)
            date_el = soup_ev.find(string=lambda s: s and any(ch.isdigit() for ch in s))
            if not start:
                start = parse_date(date_el) if date_el else None
            age_ranges = parse_age_ranges(page)
            age_min, age_max = summarize_age_ranges(age_ranges)
            title = normalize_space(title_el.get_text()) if title_el else "(Museum event)"
            fallback_date_text = normalize_space(date_el) if date_el else None
            events.append(Event(
                title=title,
                url=url,
                source="nhb",
                start=start,
                end=end,
                age_min=age_min,
                age_max=age_max,
                age_ranges=age_ranges or None,
                categories=infer_categories(
                    title=title,
                    url=url,
                    source="nhb",
                    text_blob=raw_date or (normalize_space(date_el) if date_el else ""),
                ) or None,
                raw_date=raw_date or fallback_date_text,
            ))
    return events
