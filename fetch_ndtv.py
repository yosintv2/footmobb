import json
import os
import sys
from datetime import datetime, timezone

try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
except ImportError:
    import requests as requests
    USE_CURL_CFFI = False

BASE_URL = "https://sports.ndtv.com/multisportsapi/"

PARAMS = {
    "methodtype": "3",
    "client": "2656770267",
    "sport": "1",
    "league": "0",
    "timezone": "0530",
    "language": "en",
    "widget": "sidefiltercricketSports",
}

GAMESTATES = {
    "upcoming": "2",
    "live": "1",
    "completed": "3",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sports.ndtv.com/cricket",
    "Origin": "https://sports.ndtv.com",
}


def fetch_gamestate(gs_value):
    params = {**PARAMS, "gamestate": gs_value}
    url = BASE_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    if USE_CURL_CFFI:
        r = requests.get(url, impersonate="chrome124", headers=HEADERS, timeout=30)
    else:
        r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)

    combined = {}
    total_bytes = 0

    for label, gs in GAMESTATES.items():
        try:
            data = fetch_gamestate(gs)
            combined[label] = data
            size = len(json.dumps(data))
            total_bytes += size
            print(f"  [{label}] fetched {size} chars — keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
        except Exception as e:
            print(f"  [{label}] FAILED: {e}", file=sys.stderr)
            combined[label] = {}

    combined["fetched_at"] = datetime.now(timezone.utc).isoformat()

    out_path = os.path.join(out_dir, "cricket-data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"\nSaved to {out_path} ({total_bytes} total chars)")
    print("Top-level keys saved:", list(combined.keys()))


if __name__ == "__main__":
    main()
