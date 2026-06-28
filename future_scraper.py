import asyncio
import json
import os
import pycountry
from datetime import datetime, timedelta
from curl_cffi.requests import AsyncSession

FM_BASE = "https://www.fotmob.com/api/data"

ALL_COUNTRY_CODES = [c.alpha_2 for c in pycountry.countries]
TV_BATCH_SIZE = 100
MATCH_CONCURRENCY = 3


def cleanup_old_files():
    if not os.path.exists("date"):
        os.makedirs("date")
        return

    keep_files = set()

    for offset in range(-1, 31):
        d = datetime.now() + timedelta(days=offset)

        keep_files.add(
            os.path.join(
                d.strftime("%Y"),
                d.strftime("%Y%m%d") + ".json"
            )
        )

    for root, dirs, files in os.walk("date"):
        for file in files:
            if not file.endswith(".json"):
                continue

            rel_path = os.path.relpath(
                os.path.join(root, file),
                "date"
            )

            if rel_path not in keep_files:
                try:
                    os.remove(os.path.join(root, file))
                    print(f"Deleted old file: {rel_path}")
                except Exception as e:
                    print(f"Failed deleting {rel_path}: {e}")


async def fetch_json(session, url, timeout=15):
    try:
        r = await session.get(url, impersonate="chrome120", timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


async def get_fotmob_schedule(session, date_str):
    url = (
        f"{FM_BASE}/matches"
        f"?date={date_str}"
        f"&timezone=Asia%2FTokyo"
        f"&ccode3=JPN"
        f"&includeNextDayLateNight=true"
    )

    data = await fetch_json(session, url)
    if not data:
        return []

    matches = []
    for league in data.get("leagues", []):
        league_name = league.get("name", "Unknown")
        league_id = league.get("id", 0)

        for m in league.get("matches", []):
            utc_str = m.get("status", {}).get("utcTime") or ""
            time_ts = m.get("timeTS")

            timestamp = None
            if utc_str:
                try:
                    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    timestamp = int(dt.timestamp())
                except Exception:
                    pass

            if timestamp is None and time_ts:
                timestamp = int(time_ts / 1000)

            matches.append({
                "match_id": m["id"],
                "kickoff": timestamp,
                "home_name": m["home"]["name"],
                "home_id": m["home"]["id"],
                "away_name": m["away"]["name"],
                "away_id": m["away"]["id"],
                "league": league_name,
                "league_id": league_id,
            })

    return matches


async def get_fotmob_venue(session, match_id):
    url = f"{FM_BASE}/matchDetails?matchId={match_id}"
    data = await fetch_json(session, url)
    if not data:
        return "TBA"

    ib = (data.get("content") or {}).get("matchFacts", {}).get("infoBox", {})
    stadium = ib.get("Stadium", {}) if ib else {}
    return stadium.get("name", "TBA") if stadium else "TBA"


async def fetch_tv_for_country(session, match_id, country_code):
    url = f"{FM_BASE}/tvlisting?matchId={match_id}&countryCode={country_code}"
    data = await fetch_json(session, url, timeout=5)
    if not data:
        return None

    raw = data.get("name", "")
    if not raw:
        return None

    try:
        country_name = pycountry.countries.get(alpha_2=country_code).name
    except Exception:
        country_name = country_code

    channels = [c.strip() for c in raw.split(" / ") if c.strip()]
    return {"country": country_name, "channels": sorted(set(channels))}


async def get_tv_channels(session, match_id):
    results = []

    for i in range(0, len(ALL_COUNTRY_CODES), TV_BATCH_SIZE):
        batch = ALL_COUNTRY_CODES[i:i + TV_BATCH_SIZE]
        tasks = [fetch_tv_for_country(session, match_id, cc) for cc in batch]
        batch_results = await asyncio.gather(*tasks)

        for r in batch_results:
            if r:
                results.append(r)

    return sorted(results, key=lambda x: x["country"])


async def process_one_match(session, m, index, total):
    match_id = m["match_id"]
    print(f"  [{index}/{total}] Match {match_id}: {m['home_name']} vs {m['away_name']}")

    venue_task = get_fotmob_venue(session, match_id)
    tv_task = get_tv_channels(session, match_id)

    venue, tv_channels = await asyncio.gather(venue_task, tv_task)

    return {
        "match_id": match_id,
        "kickoff": m["kickoff"],
        "fixture": f"{m['home_name']} vs {m['away_name']}",
        "league_id": m["league_id"],
        "league": m["league"],
        "venue": venue,
        "tv_channels": tv_channels,
    }


async def process_day(session, days_offset):
    target_date = datetime.now() + timedelta(days=days_offset)
    date_query = target_date.strftime("%Y-%m-%d")
    date_compact = target_date.strftime("%Y%m%d")
    file_name = date_compact + ".json"

    print(f"Processing {date_query}")

    matches = await get_fotmob_schedule(session, date_compact)
    if not matches:
        print(f"No matches found: {date_query}")
        return

    total = len(matches)
    print(f"Found {total} matches via Fotmob")

    final_data = []

    for i in range(0, total, MATCH_CONCURRENCY):
        batch = matches[i:i + MATCH_CONCURRENCY]
        tasks = [
            process_one_match(session, m, i + idx + 1, total)
            for idx, m in enumerate(batch)
        ]
        results = await asyncio.gather(*tasks)
        final_data.extend(results)
        await asyncio.sleep(1)

    year_folder = target_date.strftime("%Y")
    save_dir = os.path.join("date", year_folder)
    os.makedirs(save_dir, exist_ok=True)

    save_path = os.path.join(save_dir, file_name)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=4, ensure_ascii=False)

    print(f"Saved {year_folder}/{file_name} ({len(final_data)} matches)")


async def main():
    cleanup_old_files()

    async with AsyncSession() as session:
        for offset in range(-1, 31):
            await process_day(session, offset)
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
