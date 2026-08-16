"""Sleeper API adapter. Read-only, unauthenticated, cached to disk.

Every response is written to `data/cache/` on fetch and served from there
afterwards. Completed seasons never change, so most of this archive is fetched
exactly once and is immutable thereafter.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

V1 = "https://api.sleeper.app/v1"

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
HEADERS = {"User-Agent": "fwffl-annual/0.1 (personal use)"}
TIMEOUT = 30.0

TTL = Literal["daily", "forever"]


class FetchError(RuntimeError):
    """Network fetch failed and no cached copy exists."""


def _path(url: str, ttl: TTL) -> Path:
    # A "forever" entry keys on the URL alone; a "daily" one rolls over at midnight.
    stamp = "" if ttl == "forever" else dt.date.today().isoformat()
    digest = hashlib.sha256(f"{url}|{stamp}".encode()).hexdigest()[:16]
    hint = "".join(c if c.isalnum() else "-" for c in url.split("//", 1)[-1])[:70]
    return CACHE_DIR / f"{hint}--{digest}.json"


def get(url: str, *, ttl: TTL = "forever") -> Any:
    """Fetch JSON, preferring disk. Stale cache beats a failed run."""
    path = _path(url, ttl)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            log.warning("corrupt cache entry, refetching: %s", path)

    try:
        resp = httpx.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - any failure falls back to stale disk
        stale = sorted(CACHE_DIR.glob(f"{_path(url, 'forever').name.split('--')[0]}--*.json"))
        if stale:
            log.warning("fetch failed (%s), serving stale cache", exc)
            return json.loads(stale[-1].read_text())
        raise FetchError(f"{url}: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)  # atomic: a killed process never leaves half a file
    return payload


# --- endpoints -------------------------------------------------------------

def league(league_id: str) -> dict[str, Any]:
    return get(f"{V1}/league/{league_id}", ttl="daily")


def users(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/users", ttl="daily")


def rosters(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/rosters", ttl="daily")


def matchups(league_id: str, week: int) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/matchups/{week}")


def transactions(league_id: str, week: int) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/transactions/{week}")


def winners_bracket(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/winners_bracket")


def losers_bracket(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/losers_bracket")


def drafts(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/drafts", ttl="daily")


def draft(draft_id: str) -> dict[str, Any]:
    return get(f"{V1}/draft/{draft_id}", ttl="daily")


def draft_picks(draft_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/draft/{draft_id}/picks", ttl="daily")


def traded_picks(league_id: str) -> list[dict[str, Any]]:
    return get(f"{V1}/league/{league_id}/traded_picks", ttl="daily")


def players() -> dict[str, Any]:
    """~15MB. Refreshed daily at most."""
    return get(f"{V1}/players/nfl", ttl="daily")


def season_stats(season: str) -> dict[str, Any]:
    """Full-season NFL actuals, keyed by player id. Immutable once a season ends."""
    ttl: TTL = "forever" if int(season) < dt.date.today().year else "daily"
    return get(f"{V1}/stats/nfl/regular/{season}", ttl=ttl)
