"""Category 6 — the waiver wire: FAAB spending, bidding wars, and regret.

FAAB is $1000 a season here, which makes the bids unusually legible: a $820 bid
is 82% of a manager's entire year of ammunition spent on one player.

Failed bids are the good part. Sleeper keeps them, so every bidding war can be
reconstructed — who wanted the player, what they were willing to pay, and by how
little they missed.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..archive import Archive


def _add_names(arc: Archive, moves: pd.DataFrame) -> pd.DataFrame:
    out = moves.copy()
    out["player"] = out.adds.map(
        lambda a: ", ".join(arc.player_name(p) for p in a) if a else None
    )
    out["manager"] = out.managers.map(lambda m: m[0] if m else "Unclaimed")
    return out


def biggest_bids(arc: Archive, moves: pd.DataFrame, limit: int = 12) -> list[dict[str, Any]]:
    won = moves[(moves.type == "waiver") & (moves.status == "complete") & moves.bid.notna()]
    won = _add_names(arc, won).nlargest(limit, "bid")
    return [
        {
            "season": r.season,
            "week": r.week,
            "manager": r.manager,
            "player": r.player,
            "bid": int(r.bid),
            "share": round(r.bid / 1000 * 100, 1),
        }
        for r in won.itertuples()
    ]


def bidding_wars(arc: Archive, moves: pd.DataFrame, limit: int = 8) -> list[dict[str, Any]]:
    """Players multiple managers chased, reconstructed from failed bids."""
    waivers = moves[(moves.type == "waiver") & moves.bid.notna()].copy()
    waivers = _add_names(arc, waivers)
    waivers = waivers[waivers.player.notna()]

    wars = []
    for (season, player), group in waivers.groupby(["season", "player"]):
        if group.manager.nunique() < 2:
            continue
        winner = group[group.status == "complete"]
        if winner.empty:
            continue
        win_row = winner.iloc[0]

        # A manager can file several claims on one player; only their best counts.
        losers = (
            group[(group.status == "failed") & (group.manager != win_row.manager)]
            .groupby("manager")
            .bid.max()
            .sort_values(ascending=False)
        )

        # A losing bid *above* the winning one means Sleeper rejected it for a
        # reason other than price — almost always insufficient FAAB left. Those
        # are the best stories, so they are kept and flagged rather than dropped.
        outbid_but_failed = [
            {"manager": m, "bid": int(b)} for m, b in losers.items() if b > win_row.bid
        ]
        beaten = losers[losers <= win_row.bid]

        wars.append(
            {
                "season": season,
                "week": int(win_row.week),
                "player": player,
                "winner": win_row.manager,
                "winning_bid": int(win_row.bid),
                "contenders": int(group.manager.nunique()),
                "total_bid": int(losers.sum() + win_row.bid),
                "losers": [{"manager": m, "bid": int(b)} for m, b in losers.head(4).items()],
                "margin": int(win_row.bid - beaten.iloc[0]) if not beaten.empty else None,
                "overbid_but_failed": outbid_but_failed,
            }
        )
    wars.sort(key=lambda d: -d["total_bid"])
    return wars[:limit]


def one_that_got_away(
    arc: Archive, moves: pd.DataFrame, players: pd.DataFrame, limit: int = 12
) -> list[dict[str, Any]]:
    """Players dropped who then went on a tear — for someone else."""
    dropped = moves[(moves.status == "complete") & moves.drops.map(bool)]
    results = []
    for r in dropped.itertuples():
        for pid in r.drops:
            after = players[
                (players.season == r.season) & (players.week > r.week) & (players.pid == pid)
            ]
            if after.empty:
                continue
            points = after.points.sum()
            if points < 80:
                continue
            results.append(
                {
                    "season": r.season,
                    "week": int(r.week),
                    "manager": r.managers[0] if r.managers else "Unclaimed",
                    "player": arc.player_name(pid),
                    "position": arc.position(pid),
                    "points_after": round(float(points), 1),
                }
            )
    # One entry per manager/player/season — a player dropped twice is one story.
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for row in sorted(results, key=lambda d: -d["points_after"]):
        key = (row["season"], row["manager"], row["player"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique[:limit]


def activity(arc: Archive, moves: pd.DataFrame) -> list[dict[str, Any]]:
    """Who works the wire and who sets it and forgets it."""
    adds = moves[(moves.status == "complete") & moves.type.isin(["waiver", "free_agent"])]
    counts: dict[str, int] = {}
    seasons: dict[str, set[str]] = {}
    for r in adds.itertuples():
        for manager in r.managers:
            counts[manager] = counts.get(manager, 0) + 1
            seasons.setdefault(manager, set()).add(r.season)

    trades = moves[(moves.status == "complete") & (moves.type == "trade")]
    trade_counts: dict[str, int] = {}
    for r in trades.itertuples():
        for manager in r.managers:
            trade_counts[manager] = trade_counts.get(manager, 0) + 1

    out = [
        {
            "manager": manager,
            "moves": n,
            "seasons": len(seasons[manager]),
            "per_season": round(n / len(seasons[manager]), 1),
            "trades": trade_counts.get(manager, 0),
        }
        for manager, n in counts.items()
    ]
    out.sort(key=lambda d: -d["per_season"])
    return out


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    moves = tables["moves"]
    return {
        "biggest_bids": biggest_bids(arc, moves),
        "bidding_wars": bidding_wars(arc, moves),
        "got_away": one_that_got_away(arc, moves, tables["player_weeks"]),
        "activity": activity(arc, moves),
        "trade_counts": {
            str(season): int(n)
            for season, n in moves[(moves.type == "trade") & (moves.status == "complete")]
            .groupby("season")
            .size()
            .items()
        },
    }
