from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import pytz

SG_TZ = pytz.timezone("Asia/Singapore")
SITE_TITLE = "Singapore Social Events Weekly"
SITE_DESC = "Social and cultural events in Singapore across theatre, music, dance, museums, and more."
BASE_URL = "https://sam121.github.io/sg-kids-culture/"

SOURCE_LABELS = {
    "esplanade": "Esplanade",
    "sso": "SSO",
    "sco": "SCO",
    "artshouse": "Arts House Group",
    "wildrice": "WILD RICE",
    "srt": "Singapore Repertory Theatre",
    "practice": "The Theatre Practice",
    "gallery": "National Gallery",
    "nhb": "NHB Museums",
    "acm": "Asian Civilisations Museum",
    "sam": "Singapore Art Museum",
    "artscience": "ArtScience Museum",
    "sandstheatre": "Sands Theatre",
    "peranakan": "Peranakan Museum",
    "ihc": "Indian Heritage Centre",
    "childrensmuseum": "Children's Museum Singapore",
    "changi": "Changi Chapel & Museum",
    "bukitchandu": "Reflections at Bukit Chandu",
    "sccc": "Singapore Chinese Cultural Centre",
    "gateway": "Gateway Theatre",
}

SCRAPED_PLACE_ORDER = [
    "esplanade",
    "sso",
    "sco",
    "artshouse",
    "wildrice",
    "srt",
    "practice",
    "gallery",
    "nhb",
    "acm",
    "sam",
    "artscience",
    "sandstheatre",
    "peranakan",
    "ihc",
    "childrensmuseum",
    "bukitchandu",
    "sccc",
    "gateway",
    "changi",
]


HTML_TEMPLATE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>__SITE_TITLE__</title>
  <meta name=\"description\" content=\"__SITE_DESC__\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Space+Grotesk:wght@400;500;700&display=swap\" rel=\"stylesheet\" />
  <style>
    :root {
      --bg: #f5f2e9;
      --card: #fffdf7;
      --ink: #23262f;
      --muted: #5b6376;
      --accent: #0f766e;
      --accent-2: #ad5b27;
      --line: #d7d1c0;
      --pill: #e2f3f1;
      --shadow: 0 16px 36px rgba(31, 36, 48, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: 'Space Grotesk', system-ui, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(1200px 500px at 10% -10%, #fce9c9 0%, rgba(252, 233, 201, 0) 70%),
        radial-gradient(900px 420px at 90% 0%, #d8f1ec 0%, rgba(216, 241, 236, 0) 75%),
        linear-gradient(180deg, var(--bg) 0%, #f8f5ee 100%);
    }
    .shell { max-width: 1180px; margin: 0 auto; padding: 28px 18px 72px; }
    .topbar { display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 10px 0 18px; border-bottom: 1px solid var(--line); }
    .brand { font-weight: 700; color: var(--ink); text-decoration: none; }
    .nav { display: flex; gap: 14px; flex-wrap: wrap; }
    .nav a { color: var(--muted); text-decoration: none; font-weight: 600; }
    .nav a:hover { color: var(--ink); }
    .hero { margin-top: 18px; display: grid; grid-template-columns: 1fr; gap: 14px; align-items: stretch; }
    .hero-card { background: linear-gradient(145deg, #fffef8 0%, #f5f7fb 100%); border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow); padding: 20px; }
    h1 { margin: 0; font-family: 'Fraunces', serif; font-size: clamp(28px, 4vw, 42px); line-height: 1.1; letter-spacing: -0.4px; }
    .subtitle { margin-top: 10px; color: var(--muted); font-size: 15px; line-height: 1.6; max-width: 70ch; }
    .hero-links { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .hero-links a { border-radius: 999px; border: 1px solid var(--line); padding: 8px 12px; text-decoration: none; color: var(--ink); font-weight: 600; background: #fff; }
    .hero-links a.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
    .muted { color: var(--muted); font-size: 14px; line-height: 1.5; }
    .panel { margin-top: 18px; padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: rgba(255, 255, 255, 0.72); }
    .panel-title { font-weight: 700; letter-spacing: 0.2px; }
    .featured-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 12px; margin-top: 12px; }
    .mini-card { border: 1px solid var(--line); border-radius: 12px; padding: 12px; background: #fff; }
    .mini-title { margin: 0; font-weight: 700; font-size: 15px; color: var(--ink); text-decoration: none; }
    .mini-meta { margin-top: 6px; color: var(--muted); font-size: 13px; }
    .filter-compact { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 8px; }
    .filter-field { display: flex; flex-direction: column; gap: 4px; }
    .filter-field .muted { font-size: 12px; text-transform: uppercase; letter-spacing: 0.4px; }
    .compact-select, .compact-input {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      padding: 7px 10px;
      border-radius: 9px;
      font-weight: 600;
      font-size: 14px;
      width: 100%;
      min-width: 0;
    }
    .multi-filter { position: relative; }
    .multi-trigger {
      width: 100%;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 10px;
      padding: 9px 12px;
      font-weight: 600;
      font-size: 14px;
      line-height: 1.3;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .multi-trigger.open {
      border-color: #bdb7a5;
      box-shadow: 0 0 0 2px rgba(15, 118, 110, 0.12);
    }
    .multi-trigger-text {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      text-align: left;
      flex: 1;
    }
    .multi-caret {
      color: var(--muted);
      font-size: 12px;
      line-height: 1;
    }
    .multi-menu {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      right: 0;
      z-index: 40;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      max-height: 240px;
      overflow: auto;
      box-shadow: var(--shadow);
      padding: 6px;
    }
    .multi-option {
      width: 100%;
      border: none;
      background: #fff;
      color: var(--ink);
      border-radius: 8px;
      padding: 7px 8px;
      text-align: left;
      font-size: 14px;
      display: flex;
      align-items: center;
      gap: 8px;
      cursor: pointer;
    }
    .multi-option:hover { background: #f5f6f8; }
    .multi-option.active {
      background: #e6f4f2;
      color: #0e5d57;
      font-weight: 700;
    }
    .multi-check {
      width: 16px;
      flex: 0 0 16px;
      text-align: center;
      font-size: 12px;
    }
    .compact-input::placeholder { color: var(--muted); font-weight: 600; }
    .count { margin-top: 10px; }
    .signup {
      margin-top: 10px;
      padding: 10px 12px;
      border: 1px dashed var(--line);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.72);
      max-width: 560px;
    }
    .signup .muted { font-size: 13px; line-height: 1.45; margin-bottom: 6px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 16px; }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 16px 16px 18px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 10px; transition: transform 140ms ease, box-shadow 140ms ease; }
    .card:hover { transform: translateY(-2px); box-shadow: 0 18px 34px rgba(31, 36, 48, 0.12); }
    .title { font-weight: 700; font-size: 18px; margin: 0; color: var(--ink); text-decoration: none; }
    .meta { display: flex; flex-direction: column; gap: 6px; }
    .pill-row { display: flex; gap: 8px; flex-wrap: wrap; }
    .pill { background: var(--pill); color: var(--accent); border: 1px solid #c3e8e3; padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
    .pill-source { background: #fcefe5; color: var(--accent-2); border-color: #f2d1bb; }
    .calendar-view { margin-top: 16px; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: #fff; }
    .calendar-head { display: flex; justify-content: space-between; align-items: center; padding: 12px; border-bottom: 1px solid var(--line); background: #faf7ef; }
    .calendar-grid { width: 100%; border-collapse: collapse; table-layout: fixed; }
    .calendar-grid th { border-bottom: 1px solid var(--line); padding: 8px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.4px; }
    .calendar-grid td { vertical-align: top; min-height: 122px; height: 122px; border-top: 1px solid var(--line); border-right: 1px solid var(--line); padding: 6px; }
    .calendar-grid tr td:last-child { border-right: none; }
    .cal-day { font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 4px; }
    .cal-chip { display: block; border-radius: 8px; padding: 3px 6px; margin-top: 4px; text-decoration: none; font-size: 11px; line-height: 1.3; background: #ecf7f5; color: #0f5f59; border: 1px solid #cae7e3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .cal-more { margin-top: 4px; font-size: 11px; color: var(--muted); }
    .hidden { display: none; }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    footer { margin-top: 32px; color: var(--muted); font-size: 13px; border-top: 1px solid var(--line); padding-top: 14px; }
    @media (max-width: 980px) {
      .hero { grid-template-columns: 1fr; }
      .filter-compact { grid-template-columns: 1fr 1fr; }
      .compact-select, .compact-input { font-size: 13px; }
      .calendar-grid td { min-height: 108px; height: 108px; }
    }
    @media (max-width: 820px) {
      .filter-compact { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"topbar\">
      <a class=\"brand\" href=\"index.html\">Singapore Social Events</a>
      <div class=\"nav\">
        <a href=\"index.html\">Browse</a>
        <a href=\"about.html\">About</a>
        <a href=\"rss.xml\">RSS</a>
      </div>
    </div>

    <section class=\"hero\">
      <div class=\"hero-card\">
        <h1>__SITE_TITLE__</h1>
        <div class=\"subtitle\">A cheerful little culture scout for Singapore: I round up theatre, music, museum and festival plans, then help you filter them fast. Fresh batch lands every Monday at 9:00 AM SGT.</div>
        <div class=\"signup\">
          <div class=\"muted\">Get this list by email (Kit):</div>
          <div id=\"kit-embed\"><script async data-uid=\"c059b6fd10\" src=\"https://singaporeanculture.kit.com/c059b6fd10/index.js\"></script></div>
        </div>
        <div class=\"hero-links\">
          <a class=\"primary\" href=\"#filters\">Start Filtering</a>
          <a href=\"about.html\">How This Works</a>
          <a href=\"rss.xml\">Subscribe via RSS</a>
        </div>
      </div>
    </section>

    <section class=\"panel\" id=\"featured\">
      <div id=\"featured-title\" class=\"panel-title\">Featured This Week</div>
      <div id=\"featured-grid\" class=\"featured-grid\"></div>
      <div id=\"featured-empty\" class=\"muted hidden\">No events with clear dates in this week window.</div>
    </section>

    <div class=\"panel\" id=\"filters\">
      <div class=\"panel-title\">Filters</div>
      <div class=\"filter-compact\">
        <div class=\"filter-field\">
          <span class=\"muted\">Age</span>
          <div id=\"age-filter\" class=\"multi-filter\"></div>
        </div>
        <div class=\"filter-field\">
          <span class=\"muted\">Category</span>
          <div id=\"category-filter\" class=\"multi-filter\"></div>
        </div>
        <label class=\"filter-field\">
          <span class=\"muted\">Month</span>
          <select id=\"month-select\" class=\"compact-select\"></select>
        </label>
        <label class=\"filter-field\">
          <span class=\"muted\">View</span>
          <select id=\"view-select\" class=\"compact-select\">
            <option value=\"cards\">Card view</option>
            <option value=\"calendar\">Calendar view</option>
          </select>
        </label>
        <div class=\"filter-field\">
          <span class=\"muted\">Location</span>
          <div id=\"location-filter\" class=\"multi-filter\"></div>
        </div>
        <div class=\"filter-field\">
          <span class=\"muted\">Source</span>
          <div id=\"source-filter\" class=\"multi-filter\"></div>
        </div>
        <label class=\"filter-field\">
          <span class=\"muted\">Price Mode</span>
          <select id=\"price-mode-select\" class=\"compact-select\">
            <option value=\"all\">All prices</option>
            <option value=\"free\">Free only</option>
          </select>
        </label>
        <label class=\"filter-field\">
          <span class=\"muted\">Max S$</span>
          <input id=\"max-price\" class=\"compact-input\" type=\"number\" min=\"0\" step=\"1\" placeholder=\"e.g. 40\" />
        </label>
      </div>
      <div id=\"result-count\" class=\"muted count\"></div>
    </div>

    <div id=\"grid\" class=\"grid\"></div>
    <div id=\"calendar-view\" class=\"calendar-view hidden\"></div>

    <footer>
      <div>Generated automatically from public pages.</div>
    </footer>
  </div>

  <script>
    const events = __EVENTS_JSON__;
    const sourceLabels = __SOURCE_LABELS_JSON__;
    const ageFilterOptions = [
      { value: 'all', label: 'All ages' },
      { value: '0-5', label: '0-5' },
      { value: '6-12', label: '6-12' },
      { value: '13-17', label: '13-17' },
    ];
    const categoryFilterOptions = [
      { value: 'all', label: 'All categories' },
      { value: 'Theatre', label: 'Theatre' },
      { value: 'Opera', label: 'Opera' },
      { value: 'Orchestra', label: 'Orchestra' },
      { value: 'Cinema', label: 'Cinema' },
      { value: 'Dance', label: 'Dance' },
      { value: 'Music', label: 'Music' },
      { value: 'Workshop', label: 'Workshop' },
      { value: 'Exhibition', label: 'Exhibition' },
    ];
    const multiFilterMeta = {
      age: { containerId: 'age-filter', allLabel: 'All ages', options: ageFilterOptions },
      category: { containerId: 'category-filter', allLabel: 'All categories', options: categoryFilterOptions },
      location: { containerId: 'location-filter', allLabel: 'All locations', options: [{ value: 'all', label: 'All locations' }] },
      source: { containerId: 'source-filter', allLabel: 'All sources', options: [{ value: 'all', label: 'All sources' }] },
    };
    let openMultiKey = null;
    const grid = document.getElementById('grid');
    const calendarView = document.getElementById('calendar-view');

    function escapeHtml(value) {
      return String(value || '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function eventRanges(ev) {
      const ranges = [];
      if (Array.isArray(ev.age_ranges) && ev.age_ranges.length > 0) {
        ev.age_ranges.forEach(r => {
          if (!Array.isArray(r) || r.length < 2) return;
          const lo = r[0] === null || r[0] === undefined ? null : Number(r[0]);
          const hi = r[1] === null || r[1] === undefined ? null : Number(r[1]);
          ranges.push([Number.isNaN(lo) ? null : lo, Number.isNaN(hi) ? null : hi]);
        });
      } else if (ev.age_min !== null || ev.age_max !== null) {
        ranges.push([ev.age_min ?? null, ev.age_max ?? null]);
      }
      return ranges;
    }

    function eventCategories(ev) {
      if (!Array.isArray(ev.categories)) return [];
      return ev.categories.filter(Boolean);
    }

    function sourceLabel(source) {
      return sourceLabels[source] || source || 'Unknown source';
    }

    function eventLocation(ev) {
      if (typeof ev.venue === 'string' && ev.venue.trim()) return ev.venue.trim();
      return sourceLabel(ev.source);
    }

    function parseDateSafe(iso) {
      if (!iso) return null;
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? null : d;
    }

    function sgParts(date, opts) {
      return new Intl.DateTimeFormat('en-SG', Object.assign({ timeZone: 'Asia/Singapore' }, opts)).formatToParts(date);
    }

    function sgDateKey(date) {
      const parts = sgParts(date, { year: 'numeric', month: '2-digit', day: '2-digit' });
      const year = parts.find(p => p.type === 'year')?.value;
      const month = parts.find(p => p.type === 'month')?.value;
      const day = parts.find(p => p.type === 'day')?.value;
      return year && month && day ? `${year}-${month}-${day}` : null;
    }

    function monthKeyFromDate(date) {
      const parts = sgParts(date, { year: 'numeric', month: '2-digit' });
      const year = parts.find(p => p.type === 'year')?.value;
      const month = parts.find(p => p.type === 'month')?.value;
      return year && month ? `${year}-${month}` : null;
    }

    function keyToUtcDate(key) {
      const [y, m, d] = key.split('-').map(Number);
      if (!y || !m || !d) return null;
      return new Date(Date.UTC(y, m - 1, d));
    }

    function utcDateToKey(d) {
      const y = d.getUTCFullYear();
      const m = String(d.getUTCMonth() + 1).padStart(2, '0');
      const day = String(d.getUTCDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    }

    function addDaysKey(key, delta) {
      const d = keyToUtcDate(key);
      if (!d) return key;
      d.setUTCDate(d.getUTCDate() + delta);
      return utcDateToKey(d);
    }

    function monthLabel(key) {
      const [yy, mm] = key.split('-').map(Number);
      if (!yy || !mm) return key;
      const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return `${names[mm - 1]} ${yy}`;
    }

    function nextMonthKey(key) {
      const [yy, mm] = key.split('-').map(Number);
      if (!yy || !mm) return key;
      const month = mm === 12 ? 1 : mm + 1;
      const year = mm === 12 ? yy + 1 : yy;
      return `${year}-${String(month).padStart(2, '0')}`;
    }

    function eventDateSpan(ev) {
      const start = parseDateSafe(ev.start);
      const end = parseDateSafe(ev.end);
      if (!start && !end) return null;
      const startKey = sgDateKey(start || end);
      const endKey = sgDateKey(end || start);
      if (!startKey || !endKey) return null;
      return startKey <= endKey ? [startKey, endKey] : [endKey, startKey];
    }

    function eventMonthSpan(ev) {
      const span = eventDateSpan(ev);
      if (!span) return null;
      return [span[0].slice(0, 7), span[1].slice(0, 7)];
    }

    function allMonthKeys(rows) {
      const set = new Set();
      rows.forEach(ev => {
        const span = eventMonthSpan(ev);
        if (!span) return;
        let key = span[0];
        while (key <= span[1]) {
          set.add(key);
          const nxt = nextMonthKey(key);
          if (nxt === key) break;
          key = nxt;
        }
      });
      return Array.from(set).sort();
    }

    function bucketOverlap(r, bucket) {
      const bounds = { '0-5': [0, 5], '6-12': [6, 12], '13-17': [13, 17] }[bucket];
      if (!bounds) return true;
      const [bLo, bHi] = bounds;
      const lo = r[0] === null || r[0] === undefined ? 0 : r[0];
      const hi = r[1] === null || r[1] === undefined ? 99 : r[1];
      return lo <= bHi && hi >= bLo;
    }

    function eventBuckets(ev) {
      const ranges = eventRanges(ev);
      if (ranges.length === 0) return [];
      return ['0-5', '6-12', '13-17'].filter(b => ranges.some(r => bucketOverlap(r, b)));
    }

    function bucketLabel(ev) {
      const buckets = eventBuckets(ev);
      if (buckets.length === 0) return 'age unknown';
      const order = ['0-5', '6-12', '13-17'];
      const bounds = { '0-5': [0, 5], '6-12': [6, 12], '13-17': [13, 17] };
      const sorted = buckets.slice().sort((a, b) => order.indexOf(a) - order.indexOf(b));
      const contiguous = sorted.every((b, idx) => idx === 0 || order.indexOf(sorted[idx - 1]) + 1 === order.indexOf(b));
      if (!contiguous) return sorted.join('/');
      const first = bounds[sorted[0]][0];
      const last = bounds[sorted[sorted.length - 1]][1];
      if (first === 0 && last === 17) return 'all ages';
      return `${first}-${last}`;
    }

    function sameDayInSingapore(left, right) {
      return sgDateKey(left) === sgDateKey(right);
    }

    function isMidnightInSingapore(date) {
      const parts = sgParts(date, { hour: '2-digit', minute: '2-digit', hour12: false });
      const hh = parts.find(p => p.type === 'hour')?.value;
      const mm = parts.find(p => p.type === 'minute')?.value;
      return hh === '00' && mm === '00';
    }

    function formatDateOnly(date) {
      return date.toLocaleDateString('en-SG', { timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric' });
    }

    function formatDateTime(date) {
      return date.toLocaleString('en-SG', { timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function formatDateLabel(ev) {
      const start = parseDateSafe(ev.start);
      const end = parseDateSafe(ev.end);
      if (start && end) {
        if (sameDayInSingapore(start, end)) {
          return `On ${isMidnightInSingapore(start) ? formatDateOnly(start) : formatDateTime(start)}`;
        }
        const left = isMidnightInSingapore(start) ? formatDateOnly(start) : formatDateTime(start);
        const right = isMidnightInSingapore(end) ? formatDateOnly(end) : formatDateTime(end);
        return `Runs ${left} to ${right}`;
      }
      if (start) return `From ${isMidnightInSingapore(start) ? formatDateOnly(start) : formatDateTime(start)}`;
      if (typeof ev.raw_date === 'string' && ev.raw_date.trim()) return `Dates: ${ev.raw_date.trim()}`;
      return 'Date TBC';
    }

    function eventMinPrice(ev) {
      const txt = String(ev.price || '').trim();
      if (!txt) return null;
      if (/\bfree\b/i.test(txt)) return 0;
      const nums = txt.replace(/,/g, '').match(/\d+(?:\.\d+)?/g);
      if (!nums || nums.length === 0) return null;
      return Math.min(...nums.map(Number).filter(n => !Number.isNaN(n)));
    }

    function priceFilterLabel(mode, max) {
      if (mode === 'free') return 'Free only';
      if (max !== null && max !== undefined && !Number.isNaN(max)) return `<= S$${max}`;
      return 'All prices';
    }

    function matchesPrice(ev, mode, max) {
      const min = eventMinPrice(ev);
      if (mode === 'free') return min === 0;
      if (max !== null && max !== undefined && !Number.isNaN(max)) {
        return min !== null && min <= max;
      }
      return true;
    }

    function normalizeMultiSelection(values) {
      const list = Array.isArray(values) ? values : [values];
      const cleaned = Array.from(new Set(list.map(v => String(v || '').trim()).filter(Boolean)));
      if (cleaned.length === 0) return ['all'];
      const withoutAll = cleaned.filter(v => v !== 'all');
      return withoutAll.length > 0 ? withoutAll : ['all'];
    }

    function toggleMultiSelection(selectedValues, clickedValue) {
      if (clickedValue === 'all') return ['all'];
      const normalized = normalizeMultiSelection(selectedValues);
      let next = normalized.includes('all') ? [] : normalized.slice();
      if (next.includes(clickedValue)) {
        next = next.filter(v => v !== clickedValue);
      } else {
        next.push(clickedValue);
      }
      return normalizeMultiSelection(next);
    }

    function selectedSummary(selectedValues, options, allLabel) {
      const selected = normalizeMultiSelection(selectedValues);
      if (selected.includes('all')) return allLabel;
      const labels = selected
        .map(value => options.find(opt => opt.value === value)?.label || value)
        .filter(Boolean);
      if (labels.length === 0) return allLabel;
      const joined = labels.join(', ');
      if (labels.length > 2 || joined.length > 30) return `${labels.length} selected`;
      return joined;
    }

    function syncSelectionWithOptions(key) {
      const meta = multiFilterMeta[key];
      if (!meta) return;
      const valid = new Set(meta.options.map(opt => opt.value));
      const kept = normalizeMultiSelection(state[key]).filter(value => value === 'all' || valid.has(value));
      state[key] = normalizeMultiSelection(kept.length ? kept : ['all']);
    }

    function renderAllMultiDropdowns() {
      Object.keys(multiFilterMeta).forEach(key => renderMultiDropdown(key));
    }

    function renderMultiDropdown(key) {
      const meta = multiFilterMeta[key];
      if (!meta) return;
      const container = document.getElementById(meta.containerId);
      if (!container) return;
      syncSelectionWithOptions(key);
      const selected = normalizeMultiSelection(state[key]);
      const isOpen = openMultiKey === key;
      const triggerLabel = selectedSummary(selected, meta.options, meta.allLabel);

      container.innerHTML = `
        <button type=\"button\" class=\"multi-trigger${isOpen ? ' open' : ''}\" data-role=\"trigger\">
          <span class=\"multi-trigger-text\">${escapeHtml(triggerLabel)}</span>
          <span class=\"multi-caret\">${isOpen ? '▲' : '▼'}</span>
        </button>
        <div class=\"multi-menu${isOpen ? '' : ' hidden'}\" data-role=\"menu\">
          ${meta.options.map(opt => {
            const active = selected.includes('all') ? opt.value === 'all' : selected.includes(opt.value);
            return `
              <button type=\"button\" class=\"multi-option${active ? ' active' : ''}\" data-role=\"option\" data-value=\"${escapeHtml(opt.value)}\">
                <span class=\"multi-check\">${active ? '✓' : ''}</span>
                <span>${escapeHtml(opt.label)}</span>
              </button>
            `;
          }).join('')}
        </div>
      `;

      const trigger = container.querySelector('[data-role=\"trigger\"]');
      if (trigger) {
        trigger.addEventListener('click', ev => {
          ev.stopPropagation();
          openMultiKey = openMultiKey === key ? null : key;
          renderAllMultiDropdowns();
        });
      }

      container.querySelectorAll('[data-role=\"option\"]').forEach(btn => {
        btn.addEventListener('click', ev => {
          ev.stopPropagation();
          const value = btn.getAttribute('data-value') || 'all';
          state[key] = toggleMultiSelection(selected, value);
          openMultiKey = key;
          renderMultiDropdown(key);
          renderAll();
        });
      });
    }

    function matchesFilter(ev, filterAges, filterCategories, filterMonth, filterLocations, filterSources, filterPriceMode, filterPriceMax) {
      const ages = normalizeMultiSelection(filterAges);
      const categories = normalizeMultiSelection(filterCategories);
      const locations = normalizeMultiSelection(filterLocations);
      const sources = normalizeMultiSelection(filterSources);

      if (!ages.includes('all')) {
        const buckets = eventBuckets(ev);
        if (!ages.some(age => buckets.includes(age))) return false;
      }
      if (!categories.includes('all')) {
        const evCategories = eventCategories(ev);
        if (!categories.some(category => evCategories.includes(category))) return false;
      }
      if (filterMonth !== 'all') {
        const span = eventMonthSpan(ev);
        if (!span) return false;
        if (filterMonth < span[0] || filterMonth > span[1]) return false;
      }
      if (!locations.includes('all') && !locations.includes(eventLocation(ev))) return false;
      const source = String(ev.source || '').toLowerCase();
      if (!sources.includes('all') && !sources.includes(source)) return false;
      if (!matchesPrice(ev, filterPriceMode, filterPriceMax)) return false;
      return true;
    }

    function eventHref(ev) {
      return ev.url || ev.detail_url || '#';
    }

    function eventSort(a, b) {
      const aDate = parseDateSafe(a.start);
      const bDate = parseDateSafe(b.start);
      if (!aDate && !bDate) return String(a.title || '').localeCompare(String(b.title || ''));
      if (!aDate) return 1;
      if (!bDate) return -1;
      return aDate - bDate;
    }

    function setupMonthFilter() {
      const select = document.getElementById('month-select');
      if (!select) return;
      const keys = allMonthKeys(events);
      const current = monthKeyFromDate(new Date());
      const upcomingKeys = current ? keys.filter(k => k >= current) : keys;
      const opts = [{ value: 'all', label: 'All upcoming' }];
      if (current) opts.push({ value: current, label: `This month (${monthLabel(current)})` });
      upcomingKeys.forEach(key => {
        if (!opts.some(o => o.value === key)) opts.push({ value: key, label: monthLabel(key) });
      });
      select.innerHTML = opts.map(o => `<option value=\"${o.value}\">${escapeHtml(o.label)}</option>`).join('');
      const hasCurrentEvents = Boolean(current && keys.includes(current));
      state.month = hasCurrentEvents ? current : 'all';
      select.value = state.month;
      select.addEventListener('change', () => {
        state.month = select.value;
        renderAll();
      });
    }

    function setupLocationFilter() {
      const locations = Array.from(new Set(events.map(eventLocation))).filter(Boolean).sort((a, b) => a.localeCompare(b));
      multiFilterMeta.location.options = [{ value: 'all', label: 'All locations' }].concat(locations.map(loc => ({ value: loc, label: loc })));
      syncSelectionWithOptions('location');
      renderMultiDropdown('location');
    }

    function setupSourceFilter() {
      const sources = Array.from(new Set(events.map(ev => String(ev.source || '').toLowerCase()).filter(Boolean))).sort((a, b) => a.localeCompare(b));
      multiFilterMeta.source.options = [{ value: 'all', label: 'All sources' }].concat(sources.map(src => ({ value: src, label: sourceLabel(src) })));
      syncSelectionWithOptions('source');
      renderMultiDropdown('source');
    }

    function setupSimpleFilters() {
      const view = document.getElementById('view-select');
      const priceMode = document.getElementById('price-mode-select');
      const input = document.getElementById('max-price');
      renderAllMultiDropdowns();
      if (view) {
        view.value = state.view;
        view.addEventListener('change', () => {
          state.view = view.value || 'cards';
          renderAll();
        });
      }
      if (priceMode) {
        priceMode.value = state.priceMode;
        priceMode.addEventListener('change', () => {
          state.priceMode = priceMode.value || 'all';
          renderAll();
        });
      }
      if (input) {
        input.value = state.maxPrice ?? '';
        input.addEventListener('input', () => {
          const raw = input.value.trim();
          if (!raw) {
            state.maxPrice = null;
          } else {
            const parsed = Number(raw);
            state.maxPrice = Number.isNaN(parsed) ? null : parsed;
          }
          renderAll();
        });
      }
      document.addEventListener('click', ev => {
        const target = ev.target;
        if (!(target instanceof Element)) return;
        if (target.closest('.multi-filter')) return;
        if (openMultiKey !== null) {
          openMultiKey = null;
          renderAllMultiDropdowns();
        }
      });
      document.addEventListener('keydown', ev => {
        if (ev.key !== 'Escape') return;
        if (openMultiKey !== null) {
          openMultiKey = null;
          renderAllMultiDropdowns();
        }
      });
    }

    function weekWindowInSg() {
      const now = new Date();
      const todayKey = sgDateKey(now);
      const weekday = sgParts(now, { weekday: 'short' }).find(p => p.type === 'weekday')?.value || 'Mon';
      const map = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };
      const idx = map[weekday] || 1;
      const start = addDaysKey(todayKey, -(idx - 1));
      const end = addDaysKey(start, 6);
      return [start, end];
    }

    function shortDateKey(key, includeYear = false) {
      const d = keyToUtcDate(key);
      if (!d) return key;
      return d.toLocaleDateString('en-SG', {
        timeZone: 'Asia/Singapore',
        day: 'numeric',
        month: 'short',
        year: includeYear ? 'numeric' : undefined,
      });
    }

    function featuredWhy(ev, weekStart, weekEnd) {
      const categories = eventCategories(ev);
      const age = bucketLabel(ev);
      const minPrice = eventMinPrice(ev);
      const span = eventDateSpan(ev);
      let timing = 'it stands out in the upcoming mix';
      if (span) {
        if (span[0] >= weekStart && span[0] <= weekEnd) {
          timing = 'it starts this week';
        } else if (span[0] <= weekEnd && span[1] >= weekStart) {
          timing = 'it is running this week';
        }
      }

      const focus = categories.length ? categories.slice(0, 2).join(' + ') : 'culture';
      const reasons = [`Included because ${timing} and focuses on ${focus.toLowerCase()}`];
      if (age === 'all ages') {
        reasons.push('it works for mixed-age plans');
      } else if (age !== 'age unknown') {
        reasons.push(`it fits the ${age} bracket`);
      }
      if (minPrice === 0) reasons.push('entry is free');
      return `${reasons.join(', ')}.`;
    }

    function renderFeatured() {
      const box = document.getElementById('featured-grid');
      const empty = document.getElementById('featured-empty');
      const title = document.getElementById('featured-title');
      if (!box || !empty) return;
      const [weekStart, weekEnd] = weekWindowInSg();
      if (title) {
        title.textContent = `Featured This Week (${shortDateKey(weekStart)} - ${shortDateKey(weekEnd, true)})`;
      }
      const picked = events
        .filter(ev => {
          const span = eventDateSpan(ev);
          if (!span) return false;
          return span[0] <= weekEnd && span[1] >= weekStart;
        })
        .sort(eventSort)
        .slice(0, 6);

      if (picked.length === 0) {
        box.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      box.innerHTML = picked
        .map(ev => {
          const href = eventHref(ev);
          return `
            <article class=\"mini-card\">
              <a class=\"mini-title\" href=\"${escapeHtml(href)}\">${escapeHtml(ev.title || 'Untitled Event')}</a>
              <div class=\"mini-meta\">${escapeHtml(formatDateLabel(ev))}</div>
              <div class=\"mini-meta\">${escapeHtml(featuredWhy(ev, weekStart, weekEnd))}</div>
              <div class=\"mini-meta\">${escapeHtml(eventLocation(ev))} · ${escapeHtml(sourceLabel(ev.source))}</div>
            </article>
          `;
        })
        .join('');
    }

    function renderCards(rows) {
      grid.innerHTML = '';
      rows.forEach(ev => {
        const card = document.createElement('div');
        card.className = 'card';
        const categoryPills = eventCategories(ev).map(cat => `<span class=\"pill\">${escapeHtml(cat)}</span>`).join('');
        const href = eventHref(ev);
        const sourceUrl = ev.url ? `<span><a href=\"${escapeHtml(ev.url)}\" target=\"_blank\" rel=\"noopener\">Official listing</a></span>` : '';
        const price = ev.price ? `<span>${escapeHtml(ev.price)}</span>` : '';
        const venue = ev.venue ? `<span>${escapeHtml(ev.venue)}</span>` : '';
        card.innerHTML = `
          <div class=\"pill-row\">
            <span class=\"pill pill-source\">${escapeHtml(sourceLabel(ev.source))}</span>
            <span class=\"pill\">${escapeHtml(bucketLabel(ev))}</span>
            ${categoryPills}
          </div>
          <a class=\"title\" href=\"${escapeHtml(href)}\">${escapeHtml(ev.title || 'Untitled Event')}</a>
          <div class=\"meta muted\">
            <span>${escapeHtml(formatDateLabel(ev))}</span>
            ${venue}
            ${price}
            ${sourceUrl}
          </div>
        `;
        grid.appendChild(card);
      });
    }

    function renderCalendar(rows) {
      const monthKey = state.month !== 'all' ? state.month : (monthKeyFromDate(new Date()) || allMonthKeys(rows)[0]);
      if (!monthKey) {
        calendarView.innerHTML = '<div class=\"calendar-head\"><span>No month selected</span></div>';
        return;
      }
      const [year, month] = monthKey.split('-').map(Number);
      const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
      const first = new Date(Date.UTC(year, month - 1, 1));
      const firstDowMonday = (first.getUTCDay() + 6) % 7;
      const monthStart = `${year}-${String(month).padStart(2, '0')}-01`;
      const monthEnd = `${year}-${String(month).padStart(2, '0')}-${String(daysInMonth).padStart(2, '0')}`;

      const byDay = {};
      for (let d = 1; d <= daysInMonth; d += 1) {
        byDay[d] = [];
      }
      rows.forEach(ev => {
        const span = eventDateSpan(ev);
        if (!span) return;
        const start = span[0] < monthStart ? monthStart : span[0];
        const end = span[1] > monthEnd ? monthEnd : span[1];
        if (start > end) return;
        let key = start;
        while (key <= end) {
          const day = Number(key.slice(8, 10));
          if (byDay[day]) byDay[day].push(ev);
          const next = addDaysKey(key, 1);
          if (next === key) break;
          key = next;
        }
      });

      const names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
      const cells = [];
      for (let i = 0; i < firstDowMonday; i += 1) cells.push(null);
      for (let d = 1; d <= daysInMonth; d += 1) cells.push(d);
      while (cells.length % 7 !== 0) cells.push(null);

      let body = '';
      for (let row = 0; row < cells.length / 7; row += 1) {
        body += '<tr>';
        for (let col = 0; col < 7; col += 1) {
          const day = cells[row * 7 + col];
          if (!day) {
            body += '<td></td>';
            continue;
          }
          const items = (byDay[day] || []).slice(0, 3);
          const chips = items.map(ev => `<a class=\"cal-chip\" href=\"${escapeHtml(eventHref(ev))}\" title=\"${escapeHtml(ev.title || '')}\">${escapeHtml(ev.title || 'Untitled')}</a>`).join('');
          const extra = (byDay[day] || []).length > 3 ? `<div class=\"cal-more\">+${(byDay[day] || []).length - 3} more</div>` : '';
          body += `<td><div class=\"cal-day\">${day}</div>${chips}${extra}</td>`;
        }
        body += '</tr>';
      }

      calendarView.innerHTML = `
        <div class=\"calendar-head\">
          <strong>${escapeHtml(monthLabel(monthKey))}</strong>
          <span class=\"muted\">Showing ${rows.length} matching events</span>
        </div>
        <table class=\"calendar-grid\">
          <thead><tr>${names.map(n => `<th>${n}</th>`).join('')}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      `;
    }

    function setView(view) {
      const cards = view !== 'calendar';
      grid.classList.toggle('hidden', !cards);
      calendarView.classList.toggle('hidden', cards);
    }

    function renderAll() {
      const filtered = events
        .filter(ev => matchesFilter(ev, state.age, state.category, state.month, state.location, state.source, state.priceMode, state.maxPrice))
        .sort(eventSort);

      renderCards(filtered);
      renderCalendar(filtered);
      setView(state.view);

      const countEl = document.getElementById('result-count');
      if (countEl) {
        const monthText = state.month === 'all' ? 'All upcoming' : monthLabel(state.month);
        const ageText = state.age.includes('all') ? 'All ages' : state.age.join(', ');
        const categoryText = state.category.includes('all') ? 'All categories' : state.category.join(', ');
        const locationText = state.location.includes('all') ? 'All locations' : state.location.join(', ');
        const sourceText = state.source.includes('all') ? 'All sources' : state.source.map(sourceLabel).join(', ');
        const priceText = priceFilterLabel(state.priceMode, state.maxPrice);
        countEl.textContent = `${filtered.length} event${filtered.length === 1 ? '' : 's'} shown - ${monthText} - ${ageText} - ${categoryText} - ${locationText} - ${sourceText} - ${priceText}`;
      }
    }

    const state = {
      age: ['all'],
      category: ['all'],
      month: 'all',
      location: ['all'],
      source: ['all'],
      priceMode: 'all',
      maxPrice: null,
      view: 'cards',
    };

    setupMonthFilter();
    setupLocationFilter();
    setupSourceFilter();
    setupSimpleFilters();
    renderFeatured();
    renderAll();
  </script>
</body>
</html>
"""

ABOUT_TEMPLATE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>About - __SITE_TITLE__</title>
  <meta name=\"description\" content=\"How this event aggregator works, what it includes, and where it can miss.\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Space+Grotesk:wght@400;500;700&display=swap\" rel=\"stylesheet\" />
  <style>
    :root { --bg:#f5f2e9; --card:#fffdf7; --ink:#23262f; --muted:#5b6376; --line:#d7d1c0; --accent:#0f766e; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Space Grotesk', system-ui, sans-serif; color: var(--ink); background: linear-gradient(180deg, var(--bg) 0%, #f8f5ee 100%); }
    .shell { max-width: 920px; margin: 0 auto; padding: 28px 18px 70px; }
    .topbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; border-bottom: 1px solid var(--line); padding-bottom: 14px; }
    .topbar a { text-decoration: none; color: var(--muted); font-weight: 600; }
    .topbar a:hover { color: var(--ink); }
    .card { margin-top: 18px; background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 20px; }
    h1 { margin: 0; font-family: 'Fraunces', serif; font-size: clamp(28px, 4vw, 38px); }
    h2 { margin: 18px 0 8px; font-size: 17px; }
    p, li { color: var(--muted); line-height: 1.65; }
    ul { padding-left: 18px; margin: 8px 0 0; }
    code { background: #f1eee5; border-radius: 4px; padding: 1px 5px; }
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"topbar\">
      <a href=\"index.html\">Back to listings</a>
      <a href=\"rss.xml\">RSS</a>
    </div>
    <div class=\"card\">
      <h1>About This Feed</h1>
      <p>This project aggregates public event listings in Singapore into one filterable feed with age, category, month, location, and price filters.</p>

      <h2>Current Coverage</h2>
      <p>Configured sources: __SCRAPED_PLACES__.</p>
      <p>Sources with events in the latest build: __SOURCE_SUMMARY__.</p>
      <p>Raw events fetched: <code>__RAW_COUNT__</code>. Deduped events published: <code>__DEDUPED_COUNT__</code>.</p>

      <h2>What Was Added</h2>
      <ul>
        <li>Featured events section for the current week.</li>
        <li>Card and calendar views for easier scanning.</li>
        <li>Price filters (<code>Free only</code> and <code>Under S$X</code>).</li>
        <li>Canonical dedupe to collapse duplicate language variants.</li>
        <li>Pre-rendered event detail pages for sharing and indexing.</li>
      </ul>

      <h2>Date Handling</h2>
      <ul>
        <li><code>On ...</code> for single-date events.</li>
        <li><code>Runs ... to ...</code> when a clear start and end date are found.</li>
        <li><code>From ...</code> when only a start date is available.</li>
        <li><code>Date TBC</code> when source pages do not provide parseable dates.</li>
      </ul>

      <h2>Limitations</h2>
      <ul>
        <li>Some venues have no stable public API, so scraping depends on page structure.</li>
        <li>Listings can change quickly and may lag until the next refresh cycle.</li>
      </ul>
    </div>
  </div>
</body>
</html>
"""


DETAIL_TEMPLATE = """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>__TITLE__ | __SITE_TITLE__</title>
  <meta name=\"description\" content=\"__DESCRIPTION__\" />
  <link rel=\"canonical\" href=\"__CANONICAL__\" />
  <meta property=\"og:title\" content=\"__TITLE__\" />
  <meta property=\"og:description\" content=\"__DESCRIPTION__\" />
  <meta property=\"og:type\" content=\"article\" />
  <meta property=\"og:url\" content=\"__CANONICAL__\" />
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Space+Grotesk:wght@400;500;700&display=swap\" rel=\"stylesheet\" />
  <style>
    :root { --bg:#f5f2e9; --card:#fffdf7; --ink:#23262f; --muted:#5b6376; --line:#d7d1c0; --accent:#0f766e; --pill:#e2f3f1; }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: 'Space Grotesk', system-ui, sans-serif; color: var(--ink); background: linear-gradient(180deg, var(--bg) 0%, #f8f5ee 100%); }
    .shell { max-width: 900px; margin: 0 auto; padding: 28px 18px 70px; }
    .topbar { display: flex; justify-content: space-between; gap: 12px; border-bottom: 1px solid var(--line); padding-bottom: 14px; }
    .topbar a { text-decoration: none; color: var(--muted); font-weight: 600; }
    .card { margin-top: 18px; background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 20px; }
    h1 { margin: 0; font-family: 'Fraunces', serif; font-size: clamp(26px, 4vw, 38px); line-height: 1.15; }
    .muted { color: var(--muted); }
    .meta { margin-top: 12px; display: grid; gap: 8px; }
    .row { display: flex; gap: 10px; flex-wrap: wrap; }
    .pill { background: var(--pill); border: 1px solid #c3e8e3; color: var(--accent); border-radius: 999px; padding: 5px 10px; font-size: 12px; font-weight: 600; }
    .links { margin-top: 16px; display: flex; gap: 10px; flex-wrap: wrap; }
    .btn { border: 1px solid var(--line); border-radius: 10px; padding: 8px 12px; text-decoration: none; color: var(--ink); font-weight: 600; background: #fff; }
    .btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"topbar\">
      <a href=\"../index.html\">Back to listings</a>
      <a href=\"../about.html\">About</a>
    </div>
    <article class=\"card\">
      <h1>__TITLE__</h1>
      <div class=\"muted\">Source: __SOURCE__</div>
      <div class=\"meta\">
        <div><strong>Date:</strong> __DATE_LABEL__</div>
        <div><strong>Venue:</strong> __VENUE__</div>
        <div><strong>Price:</strong> __PRICE__</div>
        <div><strong>Age:</strong> __AGE__</div>
        <div><strong>Categories:</strong> __CATEGORIES__</div>
      </div>
      <div class=\"row\">__PILLS__</div>
      <div class=\"links\">
        <a class=\"btn primary\" href=\"__SOURCE_URL__\" target=\"_blank\" rel=\"noopener\">Open official listing</a>
        <a class=\"btn\" href=\"../index.html\">Browse more events</a>
      </div>
    </article>
  </div>
</body>
</html>
"""


def load_events(path: Path) -> List[Dict[str, Any]]:
    with path.open() as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def _parse_dt(iso: Optional[str]) -> Optional[datetime]:
    if not iso or not isinstance(iso, str):
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        txt = value.strip()
        if re.fullmatch(r"-?\d+", txt):
            return int(txt)
    return None


def _normalize_categories(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    seen: set[str] = set()
    for item in value:
        label = str(item).strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(label)
    return out


def _normalize_age_ranges(value: Any) -> List[Tuple[Optional[int], Optional[int]]]:
    if not isinstance(value, list):
        return []
    out: List[Tuple[Optional[int], Optional[int]]] = []
    seen: set[Tuple[Optional[int], Optional[int]]] = set()
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        lo = _to_int_or_none(item[0])
        hi = _to_int_or_none(item[1])
        key = (lo, hi)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _summarize_age_ranges(ranges: List[Tuple[Optional[int], Optional[int]]]) -> Tuple[Optional[int], Optional[int]]:
    if not ranges:
        return None, None
    lows = [lo for lo, _ in ranges if lo is not None]
    highs = [hi for _, hi in ranges if hi is not None]
    lo = min(lows) if lows else None
    hi = None if any(hi is None for _, hi in ranges) else (max(highs) if highs else None)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _canonical_event_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    if not parts.scheme or not parts.netloc:
        return url.strip()
    segments = [seg for seg in parts.path.split("/") if seg]
    if segments and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", segments[0], flags=re.IGNORECASE):
        segments = segments[1:]
    path = "/" + "/".join(segments)
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path or "/", "", ""))


def _normalize_title(title: Any) -> str:
    txt = str(title or "").strip().lower()
    txt = re.sub(r"\s+", " ", txt)
    txt = re.sub(r"[^a-z0-9 ]+", "", txt)
    return txt.strip()


def _event_quality(ev: Dict[str, Any]) -> int:
    score = 0
    for field in ["start", "end", "venue", "price", "raw_date", "url"]:
        if ev.get(field):
            score += 2
    if ev.get("age_min") is not None:
        score += 1
    if ev.get("age_max") is not None:
        score += 1
    score += len(ev.get("categories") or [])
    score += len(ev.get("age_ranges") or [])
    return score


def _event_signature(ev: Dict[str, Any]) -> str:
    source = str(ev.get("source") or "").strip().lower()
    title = _normalize_title(ev.get("title"))
    start = str(ev.get("start") or "").strip()
    raw_date = str(ev.get("raw_date") or "").strip()
    return f"{source}|{title}|{start}|{raw_date}"


def _merge_events(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    best = base if _event_quality(base) >= _event_quality(incoming) else incoming
    other = incoming if best is base else base
    merged = dict(best)

    for key, value in other.items():
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value

    base_start = _parse_dt(base.get("start"))
    inc_start = _parse_dt(incoming.get("start"))
    if base_start and inc_start:
        merged["start"] = min(base_start, inc_start).isoformat()
    else:
        merged["start"] = merged.get("start") or base.get("start") or incoming.get("start")

    base_end = _parse_dt(base.get("end"))
    inc_end = _parse_dt(incoming.get("end"))
    if base_end and inc_end:
        merged["end"] = max(base_end, inc_end).isoformat()
    else:
        merged["end"] = merged.get("end") or base.get("end") or incoming.get("end")

    ranges = _normalize_age_ranges(base.get("age_ranges")) + _normalize_age_ranges(incoming.get("age_ranges"))
    if base.get("age_min") is not None or base.get("age_max") is not None:
        ranges.append((_to_int_or_none(base.get("age_min")), _to_int_or_none(base.get("age_max"))))
    if incoming.get("age_min") is not None or incoming.get("age_max") is not None:
        ranges.append((_to_int_or_none(incoming.get("age_min")), _to_int_or_none(incoming.get("age_max"))))
    dedup_ranges = []
    seen_ranges = set()
    for r in ranges:
        if r in seen_ranges:
            continue
        seen_ranges.add(r)
        dedup_ranges.append(r)
    if dedup_ranges:
        merged["age_ranges"] = [[lo, hi] for lo, hi in dedup_ranges]
        lo, hi = _summarize_age_ranges(dedup_ranges)
        merged["age_min"] = lo
        merged["age_max"] = hi

    categories = _normalize_categories(base.get("categories")) + _normalize_categories(incoming.get("categories"))
    if categories:
        uniq = []
        seen_cat = set()
        for cat in categories:
            key = cat.casefold()
            if key in seen_cat:
                continue
            seen_cat.add(key)
            uniq.append(cat)
        merged["categories"] = uniq

    canonical = _canonical_event_url(merged.get("url") or "")
    if canonical:
        merged["url"] = canonical

    return merged


def _event_sort_key(ev: Dict[str, Any]) -> Tuple[int, datetime, str]:
    dt = _parse_dt(ev.get("start"))
    if dt is None:
        return (1, datetime.max.replace(tzinfo=pytz.UTC), str(ev.get("title") or "").lower())
    return (0, dt, str(ev.get("title") or "").lower())


def dedupe_and_enrich_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for row in events:
        if not isinstance(row, dict):
            continue
        ev = dict(row)
        ev["title"] = str(ev.get("title") or "").strip() or "Untitled Event"
        ev["source"] = str(ev.get("source") or "").strip().lower()
        canonical = _canonical_event_url(str(ev.get("url") or ""))
        if canonical:
            ev["url"] = canonical
        ev["categories"] = _normalize_categories(ev.get("categories"))
        ranges = _normalize_age_ranges(ev.get("age_ranges"))
        if ranges:
            ev["age_ranges"] = [[lo, hi] for lo, hi in ranges]
            lo, hi = _summarize_age_ranges(ranges)
            if ev.get("age_min") is None:
                ev["age_min"] = lo
            if ev.get("age_max") is None:
                ev["age_max"] = hi
        normalized.append(ev)

    by_primary: Dict[str, Dict[str, Any]] = {}
    for ev in normalized:
        canonical = _canonical_event_url(ev.get("url") or "")
        key = canonical or _event_signature(ev)
        if key in by_primary:
            by_primary[key] = _merge_events(by_primary[key], ev)
        else:
            by_primary[key] = ev

    by_signature: Dict[str, Dict[str, Any]] = {}
    for ev in by_primary.values():
        sig = _event_signature(ev)
        if sig in by_signature:
            by_signature[sig] = _merge_events(by_signature[sig], ev)
        else:
            by_signature[sig] = ev

    deduped = sorted(by_signature.values(), key=_event_sort_key)

    used_paths: set[str] = set()
    for ev in deduped:
        title_slug = re.sub(r"[^a-z0-9]+", "-", str(ev.get("title") or "untitled").lower()).strip("-") or "event"
        title_slug = title_slug[:80]
        start_tag = "tbc"
        dt = _parse_dt(ev.get("start"))
        if dt:
            start_tag = dt.astimezone(SG_TZ).strftime("%Y%m%d")
        digest_base = f"{ev.get('url','')}|{ev.get('source','')}|{ev.get('title','')}|{ev.get('start','')}"
        digest = hashlib.sha1(digest_base.encode("utf-8")).hexdigest()[:8]
        filename = f"{title_slug}-{start_tag}-{digest}.html"
        detail_path = f"events/{filename}"
        idx = 2
        while detail_path in used_paths:
            detail_path = f"events/{title_slug}-{start_tag}-{digest}-{idx}.html"
            idx += 1
        used_paths.add(detail_path)
        ev["detail_url"] = detail_path

    return deduped


def source_summary(events: List[Dict[str, Any]]) -> str:
    seen: List[str] = []
    for ev in events:
        src = str(ev.get("source") or "").strip().lower()
        if src and src not in seen:
            seen.append(src)
    labels = [SOURCE_LABELS.get(src, src.title()) for src in seen]
    return ", ".join(labels) if labels else "No sources"


def scraped_places_summary() -> str:
    labels = [SOURCE_LABELS.get(src, src.title()) for src in SCRAPED_PLACE_ORDER]
    return ", ".join(labels)


def _event_date_label(ev: Dict[str, Any]) -> str:
    start = _parse_dt(ev.get("start"))
    end = _parse_dt(ev.get("end"))

    def fmt(d: datetime) -> str:
        local = d.astimezone(SG_TZ)
        if local.hour == 0 and local.minute == 0:
            return local.strftime("%d %b %Y")
        return local.strftime("%d %b %Y %I:%M %p")

    if start and end:
        s = start.astimezone(SG_TZ)
        e = end.astimezone(SG_TZ)
        if s.date() == e.date():
            return f"On {fmt(start)}"
        return f"Runs {fmt(start)} to {fmt(end)}"
    if start:
        return f"From {fmt(start)}"
    raw = str(ev.get("raw_date") or "").strip()
    return f"Dates: {raw}" if raw else "Date TBC"


def _age_label(ev: Dict[str, Any]) -> str:
    ranges = _normalize_age_ranges(ev.get("age_ranges"))
    if not ranges:
        lo = _to_int_or_none(ev.get("age_min"))
        hi = _to_int_or_none(ev.get("age_max"))
        ranges = [(lo, hi)] if lo is not None or hi is not None else []
    if not ranges:
        return "Age not specified"
    labels = []
    for lo, hi in ranges:
        if lo is not None and hi is not None:
            labels.append(f"{lo}-{hi}")
        elif lo is not None:
            labels.append(f"{lo}+")
        elif hi is not None:
            labels.append(f"Up to {hi}")
        else:
            labels.append("All ages")
    return ", ".join(labels)


def render_html(events: List[Dict[str, Any]]) -> str:
    events_json = (
        json.dumps(events)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return (
        HTML_TEMPLATE.replace("__SITE_TITLE__", SITE_TITLE)
        .replace("__SITE_DESC__", SITE_DESC)
        .replace("__SCRAPED_PLACES__", scraped_places_summary())
        .replace("__SOURCE_SUMMARY__", source_summary(events))
        .replace("__UPDATED_AT__", datetime.now(tz=SG_TZ).strftime("%d %b %Y, %H:%M SGT"))
        .replace("__SOURCE_LABELS_JSON__", json.dumps(SOURCE_LABELS))
        .replace("__EVENTS_JSON__", events_json)
    )


def render_about(events: List[Dict[str, Any]], raw_count: int) -> str:
    return (
        ABOUT_TEMPLATE.replace("__SITE_TITLE__", SITE_TITLE)
        .replace("__SCRAPED_PLACES__", scraped_places_summary())
        .replace("__SOURCE_SUMMARY__", source_summary(events))
        .replace("__RAW_COUNT__", str(raw_count))
        .replace("__DEDUPED_COUNT__", str(len(events)))
    )


def render_event_page(ev: Dict[str, Any]) -> str:
    title = escape(str(ev.get("title") or "Untitled Event"))
    source = escape(SOURCE_LABELS.get(str(ev.get("source") or ""), str(ev.get("source") or "Unknown source").title()))
    source_url = escape(str(ev.get("url") or "#"))
    date_label = escape(_event_date_label(ev))
    venue = escape(str(ev.get("venue") or "Not specified"))
    price = escape(str(ev.get("price") or "Not specified"))
    age = escape(_age_label(ev))
    categories = ", ".join(_normalize_categories(ev.get("categories"))) or "Uncategorized"
    categories = escape(categories)
    canonical = escape(BASE_URL.rstrip("/") + "/" + str(ev.get("detail_url") or ""))

    desc_parts = [
        str(ev.get("venue") or "").strip(),
        str(ev.get("price") or "").strip(),
        _age_label(ev),
        ", ".join(_normalize_categories(ev.get("categories"))),
        _event_date_label(ev),
    ]
    description = escape(" | ".join([p for p in desc_parts if p]))

    pills = []
    for cat in _normalize_categories(ev.get("categories")):
        pills.append(f'<span class="pill">{escape(cat)}</span>')
    pills.append(f'<span class="pill">{source}</span>')
    pills_html = "".join(pills)

    return (
        DETAIL_TEMPLATE.replace("__TITLE__", title)
        .replace("__SITE_TITLE__", SITE_TITLE)
        .replace("__DESCRIPTION__", description)
        .replace("__CANONICAL__", canonical)
        .replace("__SOURCE__", source)
        .replace("__DATE_LABEL__", date_label)
        .replace("__VENUE__", venue)
        .replace("__PRICE__", price)
        .replace("__AGE__", age)
        .replace("__CATEGORIES__", categories)
        .replace("__PILLS__", pills_html)
        .replace("__SOURCE_URL__", source_url)
    )


def render_rss(events: List[Dict[str, Any]]) -> str:
    now = datetime.now(tz=SG_TZ)
    items = []
    for ev in events:
        start = str(ev.get("start") or "")
        title = escape(str(ev.get("title") or "Event"))
        detail_url = str(ev.get("detail_url") or "").strip()
        link = BASE_URL.rstrip("/") + "/" + detail_url if detail_url else str(ev.get("url") or "")
        age = _age_label(ev)
        category_text = ", ".join(_normalize_categories(ev.get("categories")))
        desc_parts = [str(ev.get("venue") or ""), str(ev.get("price") or ""), age, category_text]
        description = escape(" | ".join([p for p in desc_parts if p]))
        items.append(
            f"""
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <guid>{link}</guid>
      <pubDate>{start}</pubDate>
      <description><![CDATA[{description}]]></description>
    </item>"""
        )
    items_xml = "\n".join(items)
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\" ?>
<rss version=\"2.0\">
  <channel>
    <title>{SITE_TITLE}</title>
    <link>{BASE_URL}</link>
    <description>{SITE_DESC}</description>
    <lastBuildDate>{now.isoformat()}</lastBuildDate>
{items_xml}
  </channel>
</rss>
"""


def build(output_dir: Path = Path("site")):
    data_path = Path("data/events.json")
    raw_data = load_events(data_path) if data_path.exists() else []
    events = dedupe_and_enrich_events(raw_data)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(render_html(events), encoding="utf-8")
    (output_dir / "about.html").write_text(render_about(events, len(raw_data)), encoding="utf-8")
    (output_dir / "rss.xml").write_text(render_rss(events), encoding="utf-8")
    (output_dir / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    for ev in events:
        detail_url = str(ev.get("detail_url") or "").strip()
        if not detail_url:
            continue
        out_path = output_dir / detail_url
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_event_page(ev), encoding="utf-8")

    print(f"Built site with {len(events)} events ({len(raw_data)} raw) -> {output_dir}")


def main():
    build()


if __name__ == "__main__":
    main()
