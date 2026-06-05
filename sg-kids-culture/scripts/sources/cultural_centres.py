from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

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


@dataclass(frozen=True)
class VenueConfig:
    source: str
    base: str
    listings: tuple[str, ...]
    allow_terms: tuple[str, ...]
    blocked_terms: tuple[str, ...] = ()
    max_links: int = 24


CONFIGS = [
    VenueConfig(
        source="wildrice",
        base="https://www.wildrice.com.sg",
        listings=(
            "https://www.wildrice.com.sg/whats-on/",
        ),
        allow_terms=("/whats-on/", "/event/", "/events/"),
        blocked_terms=("/whats-on/page/", "/what-s-on", "/about", "/privacy", "/careers"),
    ),
    VenueConfig(
        source="srt",
        base="https://www.srt.com.sg",
        listings=(
            "https://www.srt.com.sg/",
            "https://www.srt.com.sg/index",
        ),
        allow_terms=("/whats-on", "/event", "/events", "/show", "/production", "/stage-camp"),
        blocked_terms=(
            "/about",
            "/privacy",
            "/careers",
            "/contact",
            "/blog",
            "/news",
            "/support",
            "/friends-of-srt",
            "/people-at-srt",
        ),
    ),
    VenueConfig(
        source="practice",
        base="https://www.practice.org.sg",
        listings=(
            "https://www.practice.org.sg/whats-on",
        ),
        allow_terms=("/whats-on", "/event", "/events", "/programme", "/programmes"),
        blocked_terms=("/about", "/privacy", "/careers", "/contact"),
    ),
    VenueConfig(
        source="sam",
        base="https://www.singaporeartmuseum.sg",
        listings=(
            "https://www.singaporeartmuseum.sg/art-events",
            "https://www.singaporeartmuseum.sg/Art-Events",
        ),
        allow_terms=("/art-events/", "/events/", "/event/", "/exhibition"),
    ),
    VenueConfig(
        source="artscience",
        base="https://www.marinabaysands.com",
        listings=(
            "https://www.marinabaysands.com/museum/exhibitions.html",
        ),
        allow_terms=("/museum/", "/events/", "/event/", "/exhibition", "/programmes"),
    ),
    VenueConfig(
        source="sandstheatre",
        base="https://www.marinabaysands.com",
        listings=(
            "https://www.marinabaysands.com/entertainment/shows.html",
        ),
        allow_terms=("/entertainment/", "/shows/", "/show/", "/events/", "/event/"),
        blocked_terms=("/entertainment.html",),
    ),
    VenueConfig(
        source="peranakan",
        base="https://www.nhb.gov.sg/peranakanmuseum",
        listings=(
            "https://www.nhb.gov.sg/peranakanmuseum/whatson/exhibitions",
            "https://www.nhb.gov.sg/peranakanmuseum/whatson/programmes",
        ),
        allow_terms=("/whatson/", "/events/", "/event/", "/exhibition", "/programme"),
    ),
    VenueConfig(
        source="acm",
        base="https://www.nhb.gov.sg/acm",
        listings=(
            "https://www.nhb.gov.sg/acm/whats-on/overview/",
            "https://www.nhb.gov.sg/acm/whats-on/programmes",
            "https://www.nhb.gov.sg/acm/whats-on/exhibitions",
        ),
        allow_terms=("/whats-on/", "/exhibitions/", "/programmes/", "/lectures-and-seminars/"),
        blocked_terms=("/whats-on/overview", "/view-all"),
    ),
    VenueConfig(
        source="ihc",
        base="https://www.indianheritage.gov.sg",
        listings=(
            "https://www.indianheritage.gov.sg/en/whats-on/programmes",
            "https://www.indianheritage.gov.sg/en/whats-on/exhibitions",
        ),
        allow_terms=("/whats-on/", "/events/", "/event/", "/programmes", "/exhibition"),
    ),
    VenueConfig(
        source="childrensmuseum",
        base="https://www.heritage.sg/childrensmuseum",
        listings=(
            "https://www.heritage.sg/childrensmuseum/whatson/activities",
            "https://www.heritage.sg/childrensmuseum/whatson/exhibitions",
        ),
        allow_terms=("/whatson/", "/events/", "/event/", "/programmes", "/exhibition"),
    ),
    VenueConfig(
        source="changi",
        base="https://www.changichapelmuseum.gov.sg",
        listings=(
            "https://www.changichapelmuseum.gov.sg/",
        ),
        allow_terms=("/whats-on/", "/events/", "/event/", "/programme", "/exhibition"),
    ),
    VenueConfig(
        source="bukitchandu",
        base="https://www.heritage.sg/reflectionsatbukitchandu",
        listings=(
            "https://www.heritage.sg/reflectionsatbukitchandu/whats-on/exhibitions",
            "https://www.heritage.sg/reflectionsatbukitchandu/whats-on/programmes",
        ),
        allow_terms=("/whats-on/", "/events/", "/event/", "/programmes", "/exhibition"),
    ),
    VenueConfig(
        source="sccc",
        base="https://singaporeccc.org.sg",
        listings=(
            "https://singaporeccc.org.sg/events/",
            "https://singaporeccc.org.sg/whats-on/",
        ),
        allow_terms=("/events/", "/event/", "/whats-on/", "/programme", "/programmes"),
    ),
    VenueConfig(
        source="gateway",
        base="https://gatewaytheatre.sg",
        listings=(
            "https://gatewaytheatre.sg/whats-on/",
            "https://gatewaytheatre.sg/gateway-kids-club/",
        ),
        allow_terms=("/events/", "/event/", "/whats-on/", "/gateway-kids-club"),
    ),
]

BLOCKED_FALLBACK_TITLES = {
    "what's on",
    "whats on",
    "events",
    "event",
    "programmes",
    "programme",
    "experiences",
    "exhibitions",
    "get the latest from national heritage board",
}


def _same_domain(url: str, base: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        root = urlparse(base).netloc.lower()
    except ValueError:
        return False
    return bool(host) and (host == root or host.endswith("." + root))


def _collect_links(html: str, cfg: VenueConfig) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(cfg.base, a["href"])
        if not href.startswith("http"):
            continue
        if not _same_domain(href, cfg.base):
            continue
        href_lower = href.lower()
        if not any(term in href_lower for term in cfg.allow_terms):
            continue
        if any(term in href_lower for term in cfg.blocked_terms):
            continue
        if href not in links:
            links.append(href)
        if len(links) >= cfg.max_links:
            break
    return links


def _find_date_text(page: str, soup: BeautifulSoup) -> str | None:
    # First pass: explicit date range in the full page text.
    visible_text = soup.get_text(" ", strip=True)
    start, end, raw = parse_date_range(visible_text)
    if start and end and raw:
        return raw
    date_pattern = re.compile(
        r"\b\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4}\b|(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*(?:/|,|\s+\d)",
        flags=re.IGNORECASE,
    )
    for tag in soup.find_all(["time", "p", "div", "span", "li", "h2", "h3", "h4"]):
        text = normalize_space(tag.get_text(" ", strip=True))
        if not text:
            continue
        low = text.lower()
        if any(bad in low for bad in ("last updated", "copyright", "cookie", "government of singapore")):
            continue
        if len(text) > 140:
            continue
        if date_pattern.search(text):
            return text
    return None


def _fallback_event(page: str, url: str, source: str) -> Event | None:
    soup = BeautifulSoup(page, "lxml")
    title_el = soup.find("h1") or soup.find("h2")
    title = normalize_space(title_el.get_text()) if title_el else ""
    if not title:
        return None
    if title.lower() in BLOCKED_FALLBACK_TITLES:
        return None

    visible_text = soup.get_text(" ", strip=True)
    start, end, raw_date = parse_date_range(visible_text)
    if not start:
        candidate = _find_date_text(page, soup)
        if candidate:
            start = parse_date(candidate)
            raw_date = raw_date or candidate

    age_ranges = parse_age_ranges(page)
    age_min, age_max = summarize_age_ranges(age_ranges)
    categories = infer_categories(
        title=title,
        url=url,
        source=source,
        text_blob=raw_date or "",
    )
    return Event(
        title=title,
        url=url,
        source=source,
        start=start,
        end=end,
        age_min=age_min,
        age_max=age_max,
        age_ranges=age_ranges or None,
        categories=categories or None,
        raw_date=raw_date,
    )


def fetch(max_events: int = 200) -> list[Event]:
    events: list[Event] = []
    for cfg in CONFIGS:
        for listing in cfg.listings:
            html = get(listing)
            if not html:
                continue
            events.extend(
                extract_jsonld_events(
                    html,
                    cfg.source,
                    page_url=listing,
                    fallback_age_text=html,
                )
            )
            for url in _collect_links(html, cfg):
                page = get(url)
                if not page:
                    continue
                jsonld = extract_jsonld_events(
                    page,
                    cfg.source,
                    page_url=url,
                    fallback_age_text=page,
                )
                if jsonld:
                    events.extend(jsonld)
                    continue
                fallback = _fallback_event(page, url, cfg.source)
                if fallback:
                    events.append(fallback)
                if len(events) >= max_events:
                    break
            if len(events) >= max_events:
                break
        if len(events) >= max_events:
            break
    return events
