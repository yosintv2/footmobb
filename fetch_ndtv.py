import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

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
    "live": "1",
    "upcoming": "2",
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


def pick(obj, *keys, default=None):
    for k in keys:
        if not isinstance(obj, dict):
            continue
        if "." in k:
            parts = k.split(".", 1)
            sub = obj.get(parts[0])
            if isinstance(sub, dict):
                v = sub.get(parts[1])
                if v is not None and v != "":
                    return v
        elif k in obj:
            v = obj[k]
            if v is not None and v != "":
                return v
    return default


def team_slug(name):
    """Lowercase, hyphens for spaces — used in URLs."""
    if not name:
        return "unknown"
    slug = re.sub(r"[^\w\s-]", "", name.strip().lower())
    slug = re.sub(r"\s+", "-", slug)
    return slug


def logo_url(name):
    return f"https://aimages.willow.tv/teamLogos/{team_slug(name)}.png"


def detect_duration(league="", match_type=""):
    text = (league + " " + match_type).lower()
    if "test" in text:
        return 5
    return 1


def parse_start_utc(s):
    """Convert NDTV IST string ('YYYY-MM-DD HH:mm:ss') to UTC ISO 8601."""
    if not s:
        return None
    try:
        dt_str = str(s).strip().replace(" ", "T")
        if "+" not in dt_str and "Z" not in dt_str:
            dt_str += "+05:30"
        m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\+(\d{2}):(\d{2})", dt_str)
        if m:
            naive = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")
            offset = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
            utc_dt = naive - offset
            return utc_dt.strftime("%Y-%m-%dT%H:%MZ")
    except Exception:
        pass
    return str(s)


def find_match_array(node, depth=0):
    """Recursively find the first array of match-like dicts."""
    if depth > 6:
        return None
    if isinstance(node, list) and node and isinstance(node[0], dict):
        keys = set(node[0].keys())
        team_keys = {"t1", "t2", "team1", "team2", "home", "away",
                     "t1nm", "t2nm", "team_1", "team_2", "home_team", "away_team"}
        if keys & team_keys:
            return node
    if isinstance(node, dict):
        for v in node.values():
            r = find_match_array(v, depth + 1)
            if r is not None:
                return r
    if isinstance(node, list):
        for item in node:
            r = find_match_array(item, depth + 1)
            if r is not None:
                return r
    return None


def transform_match(item):
    team1 = pick(item,
                 "t1nm", "team1_name", "home_team_name", "team1", "home",
                 "t1.name", "team_1.name", "t1.nm", "team_1.nm")
    team2 = pick(item,
                 "t2nm", "team2_name", "away_team_name", "team2", "away",
                 "t2.name", "team_2.name", "t2.nm", "team_2.nm")

    team1_logo = pick(item, "t1img", "team1_logo", "home_logo", "t1.img", "team_1.logo") or logo_url(team1)
    team2_logo = pick(item, "t2img", "team2_logo", "away_logo", "t2.img", "team_2.logo") or logo_url(team2)

    league = pick(item, "srnm", "series_name", "league", "tournament",
                  "competition", "league_name", "tournament_name", "series")

    raw_start = pick(item, "ms", "match_start", "start_time", "start",
                     "date", "match_date", "start_date", "datetime")
    start = parse_start_utc(raw_start)

    match_type = pick(item, "mtp", "match_type", "format", "title", "match_title") or ""
    duration = detect_duration(league or "", match_type)

    event_id = pick(item, "mid", "match_id", "event_id", "id", "gid")
    try:
        event_id = int(event_id) if event_id is not None else None
    except (ValueError, TypeError):
        pass

    slug = team_slug(team1) if team1 else "unknown"

    return {
        "team1": team1 or "TBD",
        "team2": team2 or "TBD",
        "team1_logo": team1_logo,
        "team2_logo": team2_logo,
        "league": league or "Cricket",
        "start": start,
        "duration": duration,
        "details_url": f"https://web.getemoji.online/?yosintv={slug}",
        "streaming_url": f"https://cdn.singhs.com.np/{slug}.json",
        "event_id": event_id,
        "cricket_data": None,
    }


def extract_matches(data):
    matches = []
    if isinstance(data, list):
        items = data
    else:
        items = find_match_array(data) or []
    for item in items:
        try:
            matches.append(transform_match(item))
        except Exception as e:
            print(f"  Warning: skipping item — {e}", file=sys.stderr)
    return matches


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(out_dir, exist_ok=True)

    all_matches = []
    seen_ids = set()

    for label, gs in GAMESTATES.items():
        try:
            data = fetch_gamestate(gs)
            size = len(json.dumps(data))
            top_keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
            print(f"  [{label}] {size} chars — top keys: {top_keys}")

            matches = extract_matches(data)
            print(f"  [{label}] → {len(matches)} matches extracted")

            for m in matches:
                eid = m.get("event_id")
                if eid is not None and eid in seen_ids:
                    continue
                if eid is not None:
                    seen_ids.add(eid)
                all_matches.append(m)

        except Exception as e:
            print(f"  [{label}] FAILED: {e}", file=sys.stderr)

    all_matches.sort(key=lambda m: m.get("start") or "")

    out_path = os.path.join(out_dir, "cricket-data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"matches": all_matches}, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(all_matches)} matches → {out_path}")


if __name__ == "__main__":
    main()
