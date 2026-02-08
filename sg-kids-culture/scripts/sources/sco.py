from __future__ import annotations

from bs4 import BeautifulSoup

from .common import Event, extract_jsonld_events, normalize_space, parse_date, parse_age_range
from .http import get

BASE = "https://sco.com.sg"
LISTING = f"{BASE}/concerts-events"


def fetch(max_events: int = 15) -> list[Event]:
    html = get(LISTING)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = BASE + href
        if href.startswith(BASE) and any(key in href for key in ["/concerts/", "/events/", "/programme/"]):
            if href not in links:
                links.append(href)
        if len(links) >= max_events:
            break

    events: list[Event] = []
    # JSON-LD on listing page
    events.extend(extract_jsonld_events(html, "sco"))

    for url in links:
        page = get(url)
        if not page:
            continue
        jsonld = extract_jsonld_events(page, "sco")
        if jsonld:
            events.extend(jsonld)
            continue
        soup_ev = BeautifulSoup(page, "lxml")
        title_el = soup_ev.find("h1")
        date_el = soup_ev.find(string=lambda s: s and any(ch.isdigit() for ch in s))
        start = parse_date(date_el) if date_el else None
        age_min, age_max = parse_age_range(page)
        events.append(Event(
            title=normalize_space(title_el.get_text()) if title_el else "(SCO event)",
            url=url,
            source="sco",
            start=start,
            age_min=age_min,
            age_max=age_max,
            raw_date=normalize_space(date_el) if date_el else None,
        ))
    return events
