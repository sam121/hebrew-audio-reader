from __future__ import annotations

from bs4 import BeautifulSoup

from .common import Event, extract_jsonld_events, normalize_space, parse_date, parse_age_range
from .http import get

NMS_BASE = "https://www.nhb.gov.sg/nationalmuseum"
NMS_LISTING = f"{NMS_BASE}/whats-on"
ACM_BASE = "https://www.nhb.gov.sg/acm"
ACM_LISTING = f"{ACM_BASE}/whats-on/programmes"


def _collect_links(html: str, base: str, limit: int = 15) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = base + href
        if href.startswith(base) and href not in links:
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
        events.extend(extract_jsonld_events(html, "nhb"))
        links = _collect_links(html, base, limit=max_events)
        for url in links:
            page = get(url)
            if not page:
                continue
            jsonld = extract_jsonld_events(page, "nhb")
            if jsonld:
                events.extend(jsonld)
                continue
            soup_ev = BeautifulSoup(page, "lxml")
            title_el = soup_ev.find("h1")
            date_el = soup_ev.find(string=lambda s: s and any(ch.isdigit() for ch in s))
            start = parse_date(date_el) if date_el else None
            age_min, age_max = parse_age_range(page)
            events.append(Event(
                title=normalize_space(title_el.get_text()) if title_el else "(Museum event)",
                url=url,
                source="nhb",
                start=start,
                age_min=age_min,
                age_max=age_max,
                raw_date=normalize_space(date_el) if date_el else None,
            ))
    return events
