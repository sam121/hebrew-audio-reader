import logging
from typing import Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SGKidsCultureBot/0.1; +https://example.com)"
}


def get(url: str, params: Optional[dict] = None) -> Optional[str]:
    try:
        resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code >= 400:
            logging.warning("GET %s failed with %s", resp.url, resp.status_code)
            return None
        return resp.text
    except requests.RequestException as exc:
        logging.warning("GET %s failed: %s", url, exc)
        return None
