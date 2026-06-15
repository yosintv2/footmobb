import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from collections import defaultdict
from curl_cffi.requests import AsyncSession

BASE = "https://www.livesoccertv.com"
OUT_DIR = "lstv"

def cleanup_old_files():
    os.makedirs(OUT_DIR, exist_ok=True)
    keep = set()
    for offset in range(-1, 13):
        d = datetime.now() + timedelta(days=offset)
        keep.add(d.strftime("%Y%m%d") + ".json")

    for f in os.listdir(OUT_DIR):
        if f.endswith(".json") and f not in keep:
            try:
                os.remove(os.path.join(OUT_DIR, f))
            except Exception:
                pass

async def fetch_text(session, url):
    r = await session.get(url, impersonate="chrome120", timeout=30)
    if r.status_code == 200:
        return r.text
    return ""

async def parse_match(session, url):
    html = await fetch_text(session, url)
    if not html:
        return None

    match_id = None
    kickoff = None

    m = re.search(r'data-current-id="(\d+)"', html)
    if m:
        match_id = int(m.group(1))

    k = re.search(r'data-kickoff="(\d+)"', html)
    if k:
        kickoff = int(k.group(1))

    title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    fixture = title.group(1).split("|")[0].strip() if title else "Unknown"

    coverage = defaultdict(set)

    for country, channel in re.findall(
        r'"publishedOn":\{"name":"(.*?)".*?"areaServed":\{"name":"(.*?)"\}',
        html,
        re.S,
    ):
        coverage[channel].add(country)

    international = []
    country_map = defaultdict(list)

    for channel, countries in coverage.items():
        for country in countries:
            country_map[country].append(channel)

    for country, channels in country_map.items():
        international.append({
            "country": country,
            "channels": sorted(set(channels))
        })

    return {
        "match_id": match_id,
        "fixture": fixture,
        "kickoff": kickoff,
        "match_url": url,
        "international_coverage": sorted(
            international,
            key=lambda x: x["country"]
        )
    }

async def process_day(session, offset):
    day = datetime.now() + timedelta(days=offset)
    date_str = day.strftime("%Y-%m-%d")

    schedule_url = f"{BASE}/schedules/{date_str}/"

    html = await fetch_text(session, schedule_url)

    urls = set(
        re.findall(
            r'https://www\.livesoccertv\.com/match/[^"\']+',
            html
        )
    )

    tasks = [parse_match(session, u.split("#")[0]) for u in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    data = [r for r in results if isinstance(r, dict)]

    file_name = day.strftime("%Y%m%d") + ".json"
    with open(os.path.join(OUT_DIR, file_name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(file_name, len(data))

async def main():
    cleanup_old_files()

    async with AsyncSession() as session:
        for offset in range(-1, 13):
            await process_day(session, offset)
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
