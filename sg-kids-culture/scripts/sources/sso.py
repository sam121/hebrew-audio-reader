from __future__ import annotations

import re
from bs4 import BeautifulSoup

from .common import (
    Event,
    extract_jsonld_events,
    infer_categories,
    normalize_space,
    parse_age_ranges,
    parse_date,
    summarize_age_ranges,
)
from .http import get

BASE = "https://www.sso.org.sg"
LISTING = f"{BASE}/whats-on"


def _extract_when_text(soup: BeautifulSoup) -> str | None:
    when_label = soup.find(
        lambda tag: tag.name in {"strong", "h3", "h4"}
        and tag.get_text(strip=True).lower() == "when"
    )
    if when_label:
        sibling = when_label.find_next_sibling()
        while sibling is not None:
            text = sibling.get_text(" ", strip=True)
            if text:
                return text
            sibling = sibling.find_next_sibling()
    # Fallback to explicit date-like sentence in visible text only.
    visible = soup.get_text("\n", strip=True)
    m = re.search(r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*/\s*\d{1,2}\s*[A-Za-z]{3}\s*\d{2,4}\s*/\s*\d{1,2}(?:\.\d{2})?\s*(?:am|pm)", visible, flags=re.IGNORECASE)
    return m.group(0) if m else None


def fetch(max_events: int = 20) -> list[Event]:
    html = get(LISTING)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("/"):
            href = BASE + href
        if href.startswith(BASE) and "/whats-on/" in href and href not in links:
            links.append(href)
        if len(links) >= max_events:
            break

    events: list[Event] = []
    # If no explicit event links found, fall back to JSON-LD on listing page
    listing_events = extract_jsonld_events(html, "sso", page_url=LISTING)
    events.extend(listing_events)

    for url in links:
        page = get(url)
        if not page:
            continue
        jsonld = extract_jsonld_events(page, "sso", page_url=url)
        if jsonld:
            events.extend(jsonld)
            continue
        soup_ev = BeautifulSoup(page, "lxml")
        title_el = soup_ev.find("h1")
        when_text = _extract_when_text(soup_ev)
        start = parse_date(when_text) if when_text else None
        age_ranges = parse_age_ranges(page)
        age_min, age_max = summarize_age_ranges(age_ranges)
        title = normalize_space(title_el.get_text()) if title_el else "(SSO event)"
        events.append(Event(
            title=title,
            url=url,
            source="sso",
            start=start,
            age_min=age_min,
            age_max=age_max,
            age_ranges=age_ranges or None,
            categories=infer_categories(
                title=title,
                url=url,
                source="sso",
                text_blob=normalize_space(when_text) if when_text else "",
            ) or None,
            raw_date=normalize_space(when_text) if when_text else None,
        ))
    return events
