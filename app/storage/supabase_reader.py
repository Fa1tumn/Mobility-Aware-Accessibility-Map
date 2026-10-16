import os
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]


def fetch_observations(env_path=None):
    load_dotenv(env_path or ROOT / ".env")
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_KEY", "").strip()
    table = os.getenv("SUPABASE_TABLE", "observations").strip()
    order = os.getenv("SUPABASE_ORDER", "record_time.asc,id.asc").strip()
    schema = os.getenv("SUPABASE_SCHEMA", "public").strip()
    token = os.getenv("SUPABASE_ACCESS_TOKEN", "").strip()
    if not url or not key or not table:
        raise ValueError("Fill in SUPABASE_URL, SUPABASE_KEY and SUPABASE_TABLE in .env.")
    if url.endswith("/rest/v1"):
        url = url[:-len("/rest/v1")]
    address = urlparse(url)
    if address.scheme != "https" or not address.netloc:
        raise ValueError("SUPABASE_URL must be an HTTPS project URL.")
    if address.path or address.query or address.fragment:
        raise ValueError("SUPABASE_URL must be the project URL or end with /rest/v1/.")
    headers = {"apikey": key, "Accept-Profile": schema}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    observations = []
    offset = 0
    with requests.Session() as session:
        while True:
            try:
                response = session.get(
                    f"{url}/rest/v1/{quote(table, safe='')}",
                    headers=headers,
                    params={"select": "*", "order": order, "limit": 1000, "offset": offset},
                    timeout=30,
                    allow_redirects=False,
                )
            except requests.RequestException:
                raise RuntimeError("Cannot connect to Supabase. Check the URL and network.") from None
            if response.status_code != 200:
                message = f"Supabase returned HTTP {response.status_code}."
                try:
                    error = response.json()
                except ValueError:
                    error = {}
                if isinstance(error, dict):
                    for field in ("code", "message", "hint"):
                        if isinstance(error.get(field), str):
                            message += f" {field}: {error[field]}"
                message += " Check the URL, table, sort columns and SELECT policy."
                for secret in (key, token):
                    if secret:
                        message = message.replace(secret, "[hidden]")
                raise RuntimeError(message)
            try:
                page = response.json()
            except ValueError:
                raise RuntimeError("Supabase did not return valid JSON.") from None
            if not isinstance(page, list) or not all(isinstance(row, dict) for row in page):
                raise ValueError("Supabase must return a list of observation records.")
            if not page:
                break
            observations.extend(page)
            offset += len(page)
    return observations
