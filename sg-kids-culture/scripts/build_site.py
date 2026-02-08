from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List

import pytz

SG_TZ = pytz.timezone("Asia/Singapore")
SITE_TITLE = "Singapore Kids Culture Weekly"
SITE_DESC = "Kid-friendly cultural events in Singapore: theatre, music, dance, museums."
BASE_URL = "https://example.github.io/sg-kids-culture"  # replace after repo is live


def load_events(path: Path) -> List[dict]:
    with path.open() as f:
        return json.load(f)


def age_bucket(ev: dict) -> str:
    lo, hi = ev.get("age_min"), ev.get("age_max")
    if lo is None and hi is None:
        return "all"
    if hi is not None and hi <= 5:
        return "0-5"
    if hi is not None and hi <= 12:
        return "6-12"
    if lo is not None and lo >= 13:
        return "13-17"
    # fallback
    return "all"


def render_html(events: List[dict]) -> str:
    # inline events for simplicity
    events_js = json.dumps(events)
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{SITE_TITLE}</title>
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
  <link href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&display=swap\" rel=\"stylesheet\" />
  <style>
    :root {{
      --bg: #0b1021;
      --card: rgba(255,255,255,0.06);
      --accent: #35d7a7;
      --text: #f6f7fb;
      --muted: #b4b7c5;
      --pill: rgba(53,215,167,0.12);
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: 'Space Grotesk', 'Inter', system-ui, sans-serif; background: radial-gradient(120% 120% at 20% 20%, #10203e 0%, #0b1021 45%, #0b0f1c 100%); color: var(--text); }}
    .shell {{ max-width: 1080px; margin: 0 auto; padding: 48px 20px 72px; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; flex-wrap: wrap; }}
    h1 {{ margin: 0; font-size: 32px; letter-spacing: -0.5px; }}
    .muted {{ color: var(--muted); font-size: 15px; line-height: 1.6; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 28px; }}
    .card {{ background: var(--card); border: 1px solid rgba(255,255,255,0.06); border-radius: 16px; padding: 16px 16px 18px; backdrop-filter: blur(4px); display: flex; flex-direction: column; gap: 10px; }}
    .title {{ font-weight: 700; font-size: 18px; margin: 0; color: #fff; }}
    .meta {{ display: flex; flex-direction: column; gap: 6px; }}
    .pill-row {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .pill {{ background: var(--pill); color: var(--accent); padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 18px; }}
    .filter-btn {{ border: 1px solid rgba(255,255,255,0.2); background: transparent; color: #fff; padding: 8px 12px; border-radius: 10px; cursor: pointer; font-weight: 600; }}
    .filter-btn.active {{ background: var(--accent); color: #0b1021; border-color: var(--accent); }}
    .signup {{ margin-top: 22px; padding: 16px; border: 1px dashed rgba(255,255,255,0.2); border-radius: 12px; }}
    footer {{ margin-top: 32px; color: var(--muted); font-size: 13px; }}
  </style>
</head>
<body>
  <div class=\"shell\">
    <header>
      <div>
        <h1>{SITE_TITLE}</h1>
        <div class=\"muted\">Weekly picks for ages 0–5, 6–12, 13–17. Updated Mondays 9:00 AM SGT.</div>
      </div>
      <div class=\"muted\"><a href=\"rss.xml\">RSS</a></div>
    </header>

    <div class=\"filters\">
      <button class=\"filter-btn active\" data-age=\"all\">All ages</button>
      <button class=\"filter-btn\" data-age=\"0-5\">0–5</button>
      <button class=\"filter-btn\" data-age=\"6-12\">6–12</button>
      <button class=\"filter-btn\" data-age=\"13-17\">13–17</button>
    </div>

    <div class=\"signup\">
      <div class=\"muted\" style=\"margin-bottom:8px;\">Get this list by email (Kit):</div>
      <div id=\"kit-embed\">Paste your Kit embed script here once you have the form ID.</div>
    </div>

    <div id=\"grid\" class=\"grid\"></div>

    <footer>
      <div>Generated automatically. Sources: Esplanade, SSO, SCO, Arts House, National Gallery, NMS/ACM.</div>
    </footer>
  </div>
  <script>
    const events = {events_js};
    const grid = document.getElementById('grid');

    function bucket(ev) {{
      const lo = ev.age_min; const hi = ev.age_max;
      if (hi !== null && hi !== undefined && hi <= 5) return '0-5';
      if (hi !== null && hi !== undefined && hi <= 12) return '6-12';
      if (lo !== null && lo !== undefined && lo >= 13) return '13-17';
      return 'all';
    }}

    function formatDate(iso) {{
      if (!iso) return 'Date TBC';
      const d = new Date(iso);
      return d.toLocaleString('en-SG', {{ timeZone: 'Asia/Singapore', weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }});
    }}

    function render(filterAge='all') {{
      grid.innerHTML = '';
      events
        .filter(ev => filterAge === 'all' || bucket(ev) === filterAge)
        .forEach(ev => {{
          const card = document.createElement('div');
          card.className = 'card';
          card.innerHTML = `
            <div class="pill-row">
              <span class="pill">${ev.source}</span>
              <span class="pill">${bucket(ev)}</span>
            </div>
            <a class="title" href="${ev.url}" target="_blank" rel="noopener">${ev.title}</a>
            <div class="meta muted">
              <span>${formatDate(ev.start)}</span>
              ${ev.venue ? `<span>${ev.venue}</span>` : ''}
              ${ev.price ? `<span>${ev.price}</span>` : ''}
            </div>
          `;
          grid.appendChild(card);
        });
    }

    document.querySelectorAll('.filter-btn').forEach(btn => {{
      btn.addEventListener('click', () => {{
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        render(btn.dataset.age);
      }});
    }});

    render();
  </script>
</body>
</html>
"""


def render_rss(events: List[dict]) -> str:
    now = datetime.now(tz=SG_TZ)
    items = []
    for ev in events:
        start = ev.get("start") or ""
        title = ev.get("title", "Event")
        link = ev.get("url", "")
        desc_parts = [ev.get("venue"), ev.get("price"), f"Ages {ev.get('age_min')}–{ev.get('age_max')}" if ev.get("age_min") else ""]
        description = " | ".join([p for p in desc_parts if p])
        items.append(f"""
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <pubDate>{start}</pubDate>
      <description><![CDATA[{description}]]></description>
    </item>""")
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
    data = load_events(Path("data/events.json")) if Path("data/events.json").exists() else []
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(render_html(data), encoding="utf-8")
    (output_dir / "rss.xml").write_text(render_rss(data), encoding="utf-8")
    (output_dir / "events.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Built site with {len(data)} events -> {output_dir}")


def main():
    build()


if __name__ == "__main__":
    main()
