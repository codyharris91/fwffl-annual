"""Category 8 — the human record: nicknames, team names, loyalties, shame.

Sleeper quietly stores every player nickname a manager has ever set, in roster
metadata, and never shows most of them again. There are hundreds in here going
back to 2021 — the richest and least-known seam in the whole archive.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pandas as pd

from ..archive import Archive
from ._common import head_to_head, regular_season


def nicknames(arc: Archive) -> dict[str, Any]:
    """Every nickname ever set, grouped by the manager who wrote it."""
    by_manager: dict[str, dict[str, Any]] = {}
    total = 0
    for season in arc.seasons:
        for uid, nicks in season.nicknames.items():
            entry = by_manager.setdefault(
                uid, {"uid": uid, "manager": arc.manager(uid), "nicknames": {}}
            )
            for pid, nick in nicks.items():
                total += 1
                # Keep the most recent spelling, but remember the first season.
                existing = entry["nicknames"].get(pid)
                entry["nicknames"][pid] = {
                    "player": arc.player_name(pid),
                    "position": arc.position(pid),
                    "nickname": nick,
                    "first_seen": existing["first_seen"] if existing else season.year,
                    "last_seen": season.year,
                }

    out = []
    for entry in by_manager.values():
        items = sorted(entry["nicknames"].values(), key=lambda d: d["first_seen"])
        out.append({"uid": entry["uid"], "manager": entry["manager"], "items": items,
                    "count": len(items)})
    out.sort(key=lambda d: -d["count"])
    return {"by_manager": out, "total_set": total, "unique": sum(d["count"] for d in out)}


def team_name_history(arc: Archive) -> list[dict[str, Any]]:
    """How each manager has rebranded, season by season."""
    out = []
    for uid, years in arc.seasons_played.items():
        names = []
        for year in years:
            season = arc.by_year[year]
            name = season.team_names.get(uid)
            if name:
                names.append({"year": year, "name": name})
        if not names:
            continue
        distinct = len({n["name"] for n in names})
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "names": names,
                "rebrands": distinct - 1,
            }
        )
    out.sort(key=lambda d: -d["rebrands"])
    return out


def ride_or_die(arc: Archive, weeks: pd.DataFrame, picks: pd.DataFrame,
                limit: int = 12) -> list[dict[str, Any]]:
    """Players a manager keeps going back to, by drafts and by weeks rostered."""
    drafted: Counter[tuple[str, str]] = Counter()
    for r in picks.itertuples():
        drafted[(r.uid, r.pid)] += 1

    held: Counter[tuple[str, str]] = Counter()
    for r in weeks.itertuples():
        for pid in json.loads(r.roster):
            held[(r.uid, pid)] += 1

    out = []
    for (uid, pid), times in drafted.items():
        if times < 2:
            continue
        out.append(
            {
                "uid": uid,
                "manager": arc.manager(uid),
                "player": arc.player_name(pid),
                "position": arc.position(pid),
                "times_drafted": times,
                "weeks_rostered": held.get((uid, pid), 0),
            }
        )
    out.sort(key=lambda d: (-d["times_drafted"], -d["weeks_rostered"]))
    return out[:limit]


def longest_tenures(arc: Archive, weeks: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    """The longest continuous manager/player marriages by weeks on the roster."""
    held: Counter[tuple[str, str]] = Counter()
    for r in weeks.itertuples():
        for pid in json.loads(r.roster):
            held[(r.uid, pid)] += 1
    out = [
        {
            "uid": uid,
            "manager": arc.manager(uid),
            "player": arc.player_name(pid),
            "position": arc.position(pid),
            "weeks": n,
        }
        for (uid, pid), n in held.most_common(limit * 3)
    ]
    return out[:limit]


def wall_of_shame(arc: Archive, weeks: pd.DataFrame) -> dict[str, Any]:
    """Losing streaks, worst seasons, and the single most miserable campaigns."""
    games = head_to_head(weeks).sort_values(["season", "uid", "week"])
    streaks = []
    for (season, uid), group in games.groupby(["season", "uid"]):
        run = worst = 0
        best_run = best = 0
        for r in group.itertuples():
            if r.lost:
                run += 1
                worst = max(worst, run)
            else:
                run = 0
            if r.won:
                best_run += 1
                best = max(best, best_run)
            else:
                best_run = 0
        streaks.append(
            {
                "season": season,
                "uid": uid,
                "manager": arc.manager(uid),
                "longest_losing": worst,
                "longest_winning": best,
            }
        )

    worst_seasons = []
    for s in arc.completed:
        for r in s.rosters:
            uid = r.get("owner_id")
            settings = r["settings"]
            total = settings["wins"] + settings["losses"]
            if not total:
                continue
            worst_seasons.append(
                {
                    "season": s.year,
                    "uid": uid,
                    "manager": arc.manager(uid),
                    "team_name": s.team_names.get(uid, ""),
                    "wins": settings["wins"],
                    "losses": settings["losses"],
                    "win_pct": round(settings["wins"] / total * 100, 1),
                    "points_for": round(settings["fpts"] + settings.get("fpts_decimal", 0) / 100, 1),
                    "record_string": (r.get("metadata") or {}).get("record", ""),
                }
            )
    worst_seasons.sort(key=lambda d: (d["win_pct"], d["points_for"]))

    return {
        "streaks": sorted(streaks, key=lambda d: -d["longest_losing"])[:10],
        "win_streaks": sorted(streaks, key=lambda d: -d["longest_winning"])[:10],
        "worst_seasons": worst_seasons[:8],
        "best_seasons": sorted(worst_seasons, key=lambda d: (-d["win_pct"], -d["points_for"]))[:8],
    }


def irony(arc: Archive) -> list[dict[str, Any]]:
    """Team names that aged badly — claims the record does not support."""
    notes = []
    for uid, years in arc.seasons_played.items():
        titles = [s.year for s in arc.completed if s.champion == uid]
        finals = [s.year for s in arc.completed if s.runner_up == uid]
        for year in years:
            name = arc.by_year[year].team_names.get(uid, "")
            lowered = name.lower()
            if any(word in lowered for word in ("champ", "dynasty", "goat")) and not titles:
                notes.append(
                    {
                        "uid": uid,
                        "manager": arc.manager(uid),
                        "year": year,
                        "team_name": name,
                        "titles": len(titles),
                        "finals_lost": len(finals),
                    }
                )
    return notes


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    weeks = tables["team_weeks"]
    return {
        "nicknames": nicknames(arc),
        "team_names": team_name_history(arc),
        "ride_or_die": ride_or_die(arc, weeks, tables["picks"]),
        "tenures": longest_tenures(arc, weeks),
        "shame": wall_of_shame(arc, weeks),
        "irony": irony(arc),
    }
