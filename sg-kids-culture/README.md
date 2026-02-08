# Singapore Kids Culture Weekly

Static site + scraper to collect kid-focused cultural events in Singapore (0–5, 6–12, 13–17). Sources: Esplanade, SSO, SCO, Arts House, National Gallery, National Museum/ACM.

## What it does
- Scrapes official event listings, normalizes to `data/events.json`.
- Builds a static site in `site/` with filters and RSS.
- Embeds a placeholder for a Kit (ConvertKit) signup form for email delivery.
- GitHub Actions workflow runs weekly on Mondays 01:00 UTC (09:00 SGT) and on pushes.

## Quick start
```bash
cd sg-kids-culture
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/scrape.py
python scripts/build_site.py
open site/index.html  # or `python -m http.server -d site 8000`
```

## Configure Kit embed
1. In Kit, create a form (free plan is fine).
2. Copy the embed snippet and replace the placeholder `<div id="kit-embed">` section in `site/index.html` (or wire a small script to inject it on build if you prefer).

## Deploy to GitHub Pages
- Enable Pages with source = GitHub Actions in repo settings.
- Workflow `.github/workflows/publish.yml` builds weekly and on push, then deploys the `site/` artifact via `actions/deploy-pages`.
- Update `BASE_URL` in `scripts/build_site.py` after you know the Pages URL (e.g., `https://<user>.github.io/<repo>`).

## Age buckets
- Derived heuristically from text/JSON-LD (`age_min`/`age_max` when available). Buckets: `0-5`, `6-12`, `13-17`, `all` fallback.

## Notes
- Scrapers prefer JSON-LD when present; otherwise fall back to basic HTML extraction. Selectors are intentionally tolerant but may need tuning per site.
- Keep runtime friendly: default caps fetch per source (15–20 links) to avoid hammering sites.
- Time zone is Singapore (`Asia/Singapore`), emails intended to go out Mondays 09:00 SGT.

## Future improvements
- Add more sources (SIFA Little, Science Centre kids programmes, CDC community arts).
- Improve age detection with NLP on descriptions.
- Add paid/free flag and price normalization.
- Add translation step (Chinese/Malay/Tamil) once a translation provider is chosen.
