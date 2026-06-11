import asyncio
import json
import os
import pycountry
from datetime import datetime, timedelta
from curl_cffi.requests import AsyncSession

SOURCE_NAME = "YoSinTV_Ultra_Engine"

channel_cache = {}


def cleanup_old_files():
    """
    Keep only yesterday, today and next 5 days JSON files.
    Delete everything else.
    """

    if not os.path.exists("date"):
        os.makedirs("date")
        return

    keep_files = set()

    for offset in range(-1, 6):
        d = datetime.now() + timedelta(days=offset)
        keep_files.add(d.strftime("%Y%m%d") + ".json")

    for file in os.listdir("date"):
        if file.endswith(".json") and file not in keep_files:
            try:
                os.remove(os.path.join("date", file))
                print(f"Deleted old file: {file}")
            except Exception as e:
                print(f"Failed deleting {file}: {e}")


async def get_channel_name(session, channel_id):
    """Fetch channel name with caching."""

    if channel_id in channel_cache:
        return channel_cache[channel_id]

    url = f"https://api.sofascore1.com/api/v1/tv/channel/{channel_id}/schedule"

    try:
        res = await session.get(
            url,
            impersonate="chrome120",
            timeout=5
        )

        if res.status_code == 200:
            name = (
                res.json()
                .get("channel", {})
                .get("name", "Unknown Channel")
            )

            channel_cache[channel_id] = name
            return name

    except Exception:
        pass

    return "Unknown Channel"


async def get_tv_data(session, match_id):
    tv_url = (
        f"https://api.sofascore1.com/api/v1/tv/event/"
        f"{match_id}/country-channels"
    )

    broadcasters = []

    try:
        res = await session.get(
            tv_url,
            impersonate="chrome120",
            timeout=10
        )

        if res.status_code != 200:
            return []

        country_channels = res.json().get("countryChannels", {})

        for country_code, channel_ids in country_channels.items():

            try:
                full_country = (
                    pycountry.countries.get(alpha_2=country_code).name
                )
            except Exception:
                full_country = country_code

            tasks = [
                get_channel_name(session, cid)
                for cid in channel_ids
            ]

            names = await asyncio.gather(*tasks)

            clean_names = sorted(
                list(
                    set(
                        n for n in names
                        if n != "Unknown Channel"
                    )
                )
            )

            broadcasters.append({
                "country": full_country,
                "channels": clean_names if clean_names else ["TBA"]
            })

        return sorted(
            broadcasters,
            key=lambda x: x["country"]
        )

    except Exception:
        return []


async def fetch_match_details(session, match_id):

    event_url = (
        f"https://api.sofascore1.com/api/v1/event/{match_id}"
    )

    try:
        res = await session.get(
            event_url,
            impersonate="chrome120",
            timeout=10
        )

        if res.status_code != 200:
            return None

        ev = res.json().get("event", {})

        home = (
            ev.get("homeTeam", {})
            .get("name", "TBA")
        )

        away = (
            ev.get("awayTeam", {})
            .get("name", "TBA")
        )

        tv_info = await get_tv_data(session, match_id)

        return {
            "match_id": ev.get("id"),
            "kickoff": ev.get("startTimestamp"),
            "fixture": f"{home} vs {away}",
            "league_id": (
                ev.get("tournament", {})
                .get("uniqueTournament", {})
                .get("id", 0)
            ),
            "league": (
                ev.get("tournament", {})
                .get("name", "Unknown")
            ),
            "venue": (
                ev.get("venue", {})
                .get("name", "TBA")
            ),
            "tv_channels": tv_info
        }

    except Exception:
        return None


async def process_day(session, days_offset):

    target_date = datetime.now() + timedelta(days=days_offset)

    date_query = target_date.strftime("%Y-%m-%d")
    file_name = target_date.strftime("%Y%m%d") + ".json"

    schedule_url = (
        f"https://api.sofascore1.com/api/v1/sport/"
        f"football/scheduled-events/{date_query}"
    )

    print(f"Processing {date_query}")

    try:
        resp = await session.get(
            schedule_url,
            impersonate="chrome120",
            timeout=30
        )

        if resp.status_code != 200:
            print(f"Failed {date_query}")
            return

        events = resp.json().get("events", [])

        tasks = [
            fetch_match_details(session, event["id"])
            for event in events
        ]

        results = await asyncio.gather(*tasks)

        final_data = [
            r for r in results
            if r is not None
        ]

        save_path = os.path.join(
            "date",
            file_name
        )

        with open(
            save_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                final_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(
            f"Saved {file_name} "
            f"({len(final_data)} matches)"
        )

    except Exception as e:
        print(f"Error {date_query}: {e}")


async def main():

    cleanup_old_files()

    async with AsyncSession() as session:

        for offset in range(-1, 6):
            await process_day(session, offset)
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
