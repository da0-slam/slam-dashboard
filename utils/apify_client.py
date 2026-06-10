"""Apify KV Store utilities for fetching influencer cover images."""
import os
import re

import requests
import streamlit as st

_APIFY_BASE = "https://api.apify.com/v2"
_COVER_RE = re.compile(r"^cover-(.+)-\d{14}-\d+\.jpg$", re.IGNORECASE)


def _token() -> str:
    return os.environ.get("APIFY_TOKEN", "").strip()


def _store_ids() -> list[str]:
    """Read APIFY_COVER_STORE_IDS env var (comma-separated store IDs)."""
    raw = os.environ.get("APIFY_COVER_STORE_IDS", "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()]


@st.cache_data(ttl=3600, show_spinner=False)
def get_cover_image_map(store_id: str) -> dict:
    """
    Returns {username_lower: image_url} for all cover-*.jpg records
    in the given Apify KV store.
    """
    token = _token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    params: dict = {"limit": 1000}
    result: dict = {}

    try:
        while True:
            resp = requests.get(
                f"{_APIFY_BASE}/key-value-stores/{store_id}/keys",
                headers=headers,
                params=params,
                timeout=10,
            )
            if resp.status_code != 200:
                break

            data = resp.json().get("data", {})
            for item in data.get("items", []):
                key = item.get("key", "")
                m = _COVER_RE.match(key)
                if m:
                    username = m.group(1).lower()
                    url = f"{_APIFY_BASE}/key-value-stores/{store_id}/records/{key}"
                    if token:
                        url += f"?token={token}"
                    result[username] = url

            next_key = data.get("nextExclusiveStartKey")
            if not next_key:
                break
            params["exclusiveStartKey"] = next_key
    except Exception:
        pass

    return result


@st.cache_data(ttl=3600, show_spinner=False)
def get_all_cover_images() -> dict:
    """
    Merge cover images from all KV stores in APIFY_COVER_STORE_IDS.
    Returns {username_lower: image_url}.
    """
    merged: dict = {}
    for sid in _store_ids():
        merged.update(get_cover_image_map(sid))
    return merged
