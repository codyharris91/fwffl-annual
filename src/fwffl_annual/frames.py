"""Tidy tables built once from the archive, reused by every stat module.

Four frames come out of here:

  `team_weeks`   one row per team per week: score, opponent, starters, bench
  `player_weeks` one row per rostered player per week: points, started, owner
  `picks`        one row per draft pick, with the player's eventual season total
  `moves`        one row per transaction, including *failed* waiver bids

Everything downstream reads these rather than the raw API payloads.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .archive import FLEX_POSITIONS, SCORING_POSITIONS, Archive, Season
from .scoring import score_all


def optimal_lineup(
    points: dict[str, float],
    slots: list[str],
    position: callable,
) -> tuple[float, list[str]]:
    """Best legal lineup from a full roster, greedily filled.

    Fixed slots are filled before FLEX, each from the highest scorer still
    available. That ordering is optimal here because FLEX accepts a superset of
    no fixed slot — every fixed slot takes exactly one position, so a player
    taken by RB could only otherwise have gone to FLEX, and the FLEX pass sees
    the next-best RB/WR/TE regardless.
    """
    pool = sorted(
        ((float(v or 0), pid, position(pid)) for pid, v in points.items()),
        reverse=True,
    )
    used: set[str] = set()
    total = 0.0
    chosen: list[str] = []

    for slot in [s for s in slots if s != "FLEX"]:
        for value, pid, pos in pool:
            if pid not in used and pos == slot:
                used.add(pid)
                total += value
                chosen.append(pid)
                break

    for _ in [s for s in slots if s == "FLEX"]:
        for value, pid, pos in pool:
            if pid not in used and pos in FLEX_POSITIONS:
                used.add(pid)
                total += value
                chosen.append(pid)
                break

    return total, chosen


def team_weeks(arc: Archive) -> pd.DataFrame:
    """One row per team per week, for every completed season."""
    rows: list[dict[str, Any]] = []
    for season in arc.completed:
        slots = season.starting_slots
        for week in range(1, season.last_scored_week + 1):
            entries = season.matchups.get(week) or []
            if not entries:
                continue

            by_matchup: dict[Any, list[dict[str, Any]]] = {}
            for m in entries:
                if m.get("matchup_id") is not None:
                    by_matchup.setdefault(m["matchup_id"], []).append(m)

            live = [m.get("points") or 0.0 for m in entries if (m.get("points") or 0) > 0]
            median = float(pd.Series(live).median()) if live else 0.0

            for m in entries:
                rid = m["roster_id"]
                uid = season.owner_of.get(rid)
                opponent = next(
                    (o for o in by_matchup.get(m.get("matchup_id"), []) if o["roster_id"] != rid),
                    None,
                )
                points = m.get("points") or 0.0
                player_points = {k: float(v or 0) for k, v in (m.get("players_points") or {}).items()}
                best, _ = optimal_lineup(player_points, slots, arc.position)

                rows.append(
                    {
                        "season": season.year,
                        "week": week,
                        "roster_id": rid,
                        "uid": uid,
                        "manager": arc.manager(uid),
                        "team_name": season.team_names.get(uid, ""),
                        "points": points,
                        "opp_roster_id": opponent["roster_id"] if opponent else None,
                        "opp_uid": season.owner_of.get(opponent["roster_id"]) if opponent else None,
                        "opp_manager": arc.who(season.year, opponent["roster_id"]) if opponent else None,
                        "opp_points": (opponent.get("points") or 0.0) if opponent else None,
                        "median": median,
                        "optimal": round(best, 2),
                        "is_playoff": week >= season.playoff_week,
                        "starters": json.dumps(m.get("starters") or []),
                        "starter_points": json.dumps(m.get("starters_points") or []),
                        "player_points": json.dumps(player_points),
                        "roster": json.dumps(m.get("players") or []),
                    }
                )

    df = pd.DataFrame(rows)
    played = df.opp_points.notna()
    df["won"] = played & (df.points > df.opp_points)
    df["lost"] = played & (df.points < df.opp_points)
    df["tied"] = played & (df.points == df.opp_points)
    df["margin"] = df.points - df.opp_points
    df["left_on_bench"] = (df.optimal - df.points).round(2)
    df["efficiency"] = (df.points / df.optimal * 100).where(df.optimal > 0).round(1)
    return df


def player_weeks(arc: Archive, weeks: pd.DataFrame) -> pd.DataFrame:
    """One row per rostered player per week: what they scored and who held them."""
    rows: list[dict[str, Any]] = []
    for row in weeks.itertuples():
        started = set(json.loads(row.starters))
        for pid, value in json.loads(row.player_points).items():
            rows.append(
                {
                    "season": row.season,
                    "week": row.week,
                    "pid": pid,
                    "points": float(value or 0),
                    "started": pid in started,
                    "uid": row.uid,
                    "manager": row.manager,
                    "is_playoff": row.is_playoff,
                }
            )
    df = pd.DataFrame(rows)
    df["player"] = df.pid.map(arc.player_name)
    df["position"] = df.pid.map(arc.position)
    return df


def season_totals(arc: Archive) -> dict[str, dict[str, float]]:
    """year -> {player_id: league-scored season total} for the whole NFL.

    Scored from Sleeper's season stat lines under this league's settings, so it
    covers players nobody rostered — which is what makes "best undrafted player"
    and honest draft-value math possible.
    """
    return {
        year: score_all(stats, arc.by_year[year].scoring)
        for year, stats in arc.season_stats.items()
    }


def picks(arc: Archive, totals: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Every draft pick, with what the player actually went on to score."""
    rows: list[dict[str, Any]] = []
    for season in arc.completed:
        scored = totals.get(season.year, {})
        eligible = {
            pid: pts for pid, pts in scored.items() if arc.position(pid) in SCORING_POSITIONS
        }
        order = sorted(eligible.items(), key=lambda kv: -kv[1])
        overall_rank = {pid: i + 1 for i, (pid, _) in enumerate(order)}

        # Rank within position too — the fair way to judge a pick, since a QB
        # and an RB taken at the same slot are never competing for the same job.
        position_rank: dict[str, int] = {}
        seen: dict[str, int] = {}
        for pid, _ in order:
            pos = arc.position(pid)
            seen[pos] = seen.get(pos, 0) + 1
            position_rank[pid] = seen[pos]

        for p in season.draft_picks:
            pid = p["player_id"]
            rows.append(
                {
                    "season": season.year,
                    "pick": p["pick_no"],
                    "round": p["round"],
                    "slot": p["draft_slot"],
                    "roster_id": p["roster_id"],
                    "uid": season.owner_of.get(p["roster_id"]),
                    "manager": arc.who(season.year, p["roster_id"]),
                    "pid": pid,
                    "player": arc.player_name(pid),
                    "position": arc.position(pid),
                    "points": eligible.get(pid, 0.0),
                    "overall_rank": overall_rank.get(pid),
                    "position_rank": position_rank.get(pid),
                    "teams": season.teams,
                }
            )
    return pd.DataFrame(rows)


def moves(arc: Archive) -> pd.DataFrame:
    """Every transaction, including failed waiver claims."""
    rows: list[dict[str, Any]] = []
    for season in arc.completed:
        for week, entries in season.transactions.items():
            for t in entries:
                roster_ids = t.get("roster_ids") or []
                rows.append(
                    {
                        "season": season.year,
                        "week": week,
                        "type": t["type"],
                        "status": t["status"],
                        "created": t.get("created"),
                        "roster_ids": tuple(roster_ids),
                        "managers": tuple(arc.who(season.year, r) for r in roster_ids),
                        "bid": (t.get("settings") or {}).get("waiver_bid"),
                        "adds": t.get("adds") or {},
                        "drops": t.get("drops") or {},
                        "draft_picks": t.get("draft_picks") or [],
                    }
                )
    return pd.DataFrame(rows)


def build_all(arc: Archive) -> dict[str, Any]:
    weeks = team_weeks(arc)
    totals = season_totals(arc)
    return {
        "team_weeks": weeks,
        "player_weeks": player_weeks(arc, weeks),
        "season_totals": totals,
        "picks": picks(arc, totals),
        "moves": moves(arc),
    }
