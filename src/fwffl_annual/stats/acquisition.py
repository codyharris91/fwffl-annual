"""How rosters actually get built: draft, trade, or the waiver wire.

Every point a team scores arrived through one of three doors. This module works
out which, by replaying each season's acquisitions in order.

The unit throughout is the **started point** — points a player actually put into
a lineup for the team that acquired him. Points on a bench are not value
delivered, and a great pickup nobody starts did not help anyone. That choice is
what makes the three channels comparable.

Attribution follows the player, not the transaction: a receiver drafted in round
two, traded in week 6 and dropped in week 10 is credited to the draft for weeks
1–5 and to the trade for weeks 6–9. Re-acquiring a player you once cut starts a
fresh attribution, so nobody gets draft credit for a player they let go.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import pandas as pd

from ..archive import Archive

# Waiver claims and plain free-agent adds are one channel: both are players who
# were available to the whole league and somebody chose to go and get them.
WIRE_TYPES = frozenset({"waiver", "free_agent"})

SOURCES = ("draft", "trade", "waiver")
SOURCE_LABELS = {"draft": "Draft", "trade": "Trades", "waiver": "Waiver wire"}

# A trade needs to return this much more than it gave up before it is called a
# win rather than a wash — roughly a useful starter's half-season.
DECISIVE_MARGIN = 40.0


def _events(arc: Archive, season) -> dict[tuple[int, str], list[dict[str, Any]]]:
    """(roster_id, player_id) -> acquisition events, earliest first.

    Week 0 holds the draft; every later event is a transaction that put the
    player on that roster.
    """
    events: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)

    for pick in season.draft_picks:
        events[(pick["roster_id"], pick["player_id"])].append(
            {"week": 0, "source": "draft", "txn": f"draft-{season.year}", "pick": pick["pick_no"]}
        )

    for week, entries in sorted(season.transactions.items()):
        for txn in entries:
            if txn["status"] != "complete":
                continue
            adds = txn.get("adds") or {}
            if txn["type"] == "trade":
                source = "trade"
            elif txn["type"] in WIRE_TYPES:
                source = "waiver"
            else:
                continue  # commissioner edits are not an acquisition channel
            for pid, roster_id in adds.items():
                events[(roster_id, pid)].append(
                    {
                        "week": week,
                        "source": source,
                        "txn": txn["transaction_id"],
                        "bid": (txn.get("settings") or {}).get("waiver_bid"),
                    }
                )

    for key in events:
        events[key].sort(key=lambda e: e["week"])
    return events


def attribute(arc: Archive, weeks: pd.DataFrame) -> pd.DataFrame:
    """One row per rostered player-week, tagged with how he was acquired."""
    rows: list[dict[str, Any]] = []

    for season in arc.completed:
        events = _events(arc, season)
        season_weeks = weeks[weeks.season == season.year]

        for row in season_weeks.itertuples():
            starters = set(json.loads(row.starters))
            starter_points = dict(
                zip(json.loads(row.starters), json.loads(row.starter_points), strict=False)
            )
            for pid in json.loads(row.roster):
                history = events.get((row.roster_id, pid), [])
                # The acquisition in force this week is the latest one before it.
                current = None
                for event in history:
                    if event["week"] <= row.week:
                        current = event
                    else:
                        break
                if current is None:
                    # On the roster with no recorded acquisition: pre-2021 holdovers
                    # and the odd commissioner move. Rare, and never attributed.
                    continue
                started = pid in starters
                rows.append(
                    {
                        "season": season.year,
                        "week": row.week,
                        "roster_id": row.roster_id,
                        "uid": row.uid,
                        "manager": row.manager,
                        "pid": pid,
                        "source": current["source"],
                        "txn": current["txn"],
                        "acquired_week": current["week"],
                        "started": started,
                        "points": float(starter_points.get(pid, 0.0)) if started else 0.0,
                        "is_playoff": row.is_playoff,
                    }
                )

    frame = pd.DataFrame(rows)
    frame["player"] = frame.pid.map(arc.player_name)
    frame["position"] = frame.pid.map(arc.position)
    return frame


def channel_share(arc: Archive, tagged: pd.DataFrame) -> dict[str, Any]:
    """What share of started points each channel delivers, league-wide and per manager."""
    started = tagged[tagged.started]

    league_total = started.points.sum()
    league = [
        {
            "source": source,
            "label": SOURCE_LABELS[source],
            "points": round(float(started[started.source == source].points.sum()), 1),
            "share": round(float(started[started.source == source].points.sum()) / league_total * 100, 1),
            "starts": int((started.source == source).sum()),
        }
        for source in SOURCES
    ]

    per_manager = []
    for uid, group in started.groupby("uid"):
        total = group.points.sum()
        entry = {
            "uid": uid,
            "manager": arc.manager(uid),
            "points": round(float(total), 1),
            "seasons": int(group.season.nunique()),
        }
        for source in SOURCES:
            share = group[group.source == source].points.sum() / total * 100
            entry[source] = round(float(share), 1)
            entry[f"{source}_points"] = round(float(group[group.source == source].points.sum()), 1)
        per_manager.append(entry)
    per_manager.sort(key=lambda d: -d["draft"])

    by_season = []
    for year, group in started.groupby("season"):
        total = group.points.sum()
        row = {"season": year}
        for source in SOURCES:
            row[source] = round(float(group[group.source == source].points.sum() / total * 100), 1)
        by_season.append(row)
    by_season.sort(key=lambda d: d["season"])

    return {"league": league, "by_manager": per_manager, "by_season": by_season}


def _haul(tagged: pd.DataFrame, txn_id: str, roster_id: int) -> pd.DataFrame:
    return tagged[(tagged.txn == txn_id) & (tagged.roster_id == roster_id) & tagged.started]


def trades(arc: Archive, tagged: pd.DataFrame) -> list[dict[str, Any]]:
    """Every trade, scored by what each side's haul went on to start for them.

    A trade is judged only on points the acquired players actually put into a
    lineup afterwards. Nothing is charged for the players given up: their later
    output is already counted as the other side's return, so counting it twice
    would double the size of every verdict.
    """
    out: list[dict[str, Any]] = []

    for season in arc.completed:
        for week, entries in sorted(season.transactions.items()):
            for txn in entries:
                if txn["type"] != "trade" or txn["status"] != "complete":
                    continue
                roster_ids = txn.get("roster_ids") or []
                if len(roster_ids) != 2:
                    continue
                adds = txn.get("adds") or {}
                txn_id = txn["transaction_id"]

                sides = []
                for roster_id in roster_ids:
                    received = [pid for pid, rid in adds.items() if rid == roster_id]
                    haul = _haul(tagged, txn_id, roster_id)
                    by_player = haul.groupby("pid").points.sum().to_dict()
                    sides.append(
                        {
                            "roster_id": roster_id,
                            "uid": season.owner_of.get(roster_id),
                            "manager": arc.who(season.year, roster_id),
                            "received": [
                                {
                                    "player": arc.player_name(pid),
                                    "position": arc.position(pid),
                                    "points": round(float(by_player.get(pid, 0.0)), 1),
                                }
                                for pid in sorted(received, key=lambda p: -by_player.get(p, 0.0))
                            ],
                            "points": round(float(haul.points.sum()), 1),
                            "starts": int(len(haul)),
                        }
                    )

                sides.sort(key=lambda s: -s["points"])
                winner, loser = sides
                margin = round(winner["points"] - loser["points"], 1)
                out.append(
                    {
                        "season": season.year,
                        "week": week,
                        "txn": txn_id,
                        "sides": sides,
                        "margin": margin,
                        "total_points": round(winner["points"] + loser["points"], 1),
                        "decisive": margin >= DECISIVE_MARGIN,
                        "picks_involved": bool(txn.get("draft_picks")),
                        "faab_involved": bool(txn.get("waiver_budget")),
                        "players": sum(len(s["received"]) for s in sides),
                    }
                )
    out.sort(key=lambda d: -d["margin"])
    return out


def trade_ledger(arc: Archive, deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each manager's record as a trader: what they took in, and what they gave up."""
    tally: dict[str, dict[str, Any]] = {}

    for deal in deals:
        for index, side in enumerate(deal["sides"]):
            other = deal["sides"][1 - index]
            uid = side["uid"]
            if uid is None:
                continue
            entry = tally.setdefault(
                uid,
                {
                    "uid": uid,
                    "manager": arc.manager(uid),
                    "trades": 0,
                    "gained": 0.0,
                    "surrendered": 0.0,
                    "won": 0,
                    "lost": 0,
                    "washes": 0,
                },
            )
            entry["trades"] += 1
            entry["gained"] += side["points"]
            entry["surrendered"] += other["points"]
            if not deal["decisive"]:
                entry["washes"] += 1
            elif side["points"] > other["points"]:
                entry["won"] += 1
            else:
                entry["lost"] += 1

    out = []
    for entry in tally.values():
        entry["gained"] = round(entry["gained"], 1)
        entry["surrendered"] = round(entry["surrendered"], 1)
        entry["net"] = round(entry["gained"] - entry["surrendered"], 1)
        entry["net_per_trade"] = round(entry["net"] / entry["trades"], 1)
        out.append(entry)
    out.sort(key=lambda d: -d["net"])
    return out


def waiver_hits(arc: Archive, tagged: pd.DataFrame, tables: dict[str, Any],
                limit: int = 15) -> dict[str, Any]:
    """The best pickups off the wire, and what they cost."""
    moves = tables["moves"]
    bids: dict[str, float] = {}
    for row in moves.itertuples():
        if row.status == "complete" and row.type in WIRE_TYPES:
            for pid in row.adds:
                bids[f"{row.season}:{pid}:{row.week}"] = row.bid

    wire = tagged[(tagged.source == "waiver") & tagged.started]
    grouped = wire.groupby(["txn", "season", "manager", "pid", "acquired_week"]).agg(
        points=("points", "sum"), starts=("points", "size")
    ).reset_index()

    hits = []
    for row in grouped.itertuples():
        bid = bids.get(f"{row.season}:{row.pid}:{row.acquired_week}")
        hits.append(
            {
                "season": row.season,
                "week": int(row.acquired_week),
                "manager": row.manager,
                "player": arc.player_name(row.pid),
                "position": arc.position(row.pid),
                "points": round(float(row.points), 1),
                "starts": int(row.starts),
                "bid": None if bid is None or pd.isna(bid) else int(bid),
            }
        )
    hits.sort(key=lambda d: -d["points"])

    paid = [h for h in hits if h["bid"]]
    for hit in paid:
        hit["points_per_100"] = round(hit["points"] / hit["bid"] * 100, 1)
    bargains = sorted([h for h in paid if h["bid"] >= 25], key=lambda d: -d["points_per_100"])
    busts = sorted([h for h in paid if h["bid"] >= 200], key=lambda d: d["points"])

    free = [h for h in hits if not h["bid"]]

    return {
        "best": hits[:limit],
        "bargains": bargains[:10],
        "busts": busts[:10],
        "free_finds": free[:10],
        "total_wire_points": round(float(wire.points.sum()), 1),
    }


def season_profiles(arc: Archive, tagged: pd.DataFrame, tables: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per manager-season: how the roster was built, and how it finished."""
    from .draft import with_value

    picks = with_value(tables["picks"])
    draft_value = picks.groupby(["season", "uid"]).value.sum().to_dict()
    started = tagged[tagged.started]

    rows: list[dict[str, Any]] = []
    for season in arc.completed:
        standings = sorted(
            (
                (
                    roster.get("owner_id"),
                    roster["settings"]["wins"],
                    roster["settings"]["fpts"] + roster["settings"].get("fpts_decimal", 0) / 100,
                )
                for roster in season.rosters
            ),
            key=lambda t: (-t[1], -t[2]),
        )
        finish = {uid: i + 1 for i, (uid, _, _) in enumerate(standings)}
        wins = {uid: w for uid, w, _ in standings}

        for uid in finish:
            mine = started[(started.season == season.year) & (started.uid == uid)]
            total = float(mine.points.sum())
            if not total:
                continue
            entry = {
                "season": season.year,
                "uid": uid,
                "manager": arc.manager(uid),
                "team_name": season.team_names.get(uid, ""),
                "points": round(total, 1),
                "wins": wins[uid],
                "finish": finish[uid],
                "teams": season.teams,
                "made_playoffs": uid in season.playoff_teams,
                "champion": uid == season.champion,
                "draft_value": round(float(draft_value.get((season.year, uid), 0.0)), 1),
            }
            for source in SOURCES:
                points = float(mine[mine.source == source].points.sum())
                entry[f"{source}_points"] = round(points, 1)
                entry[source] = round(points / total * 100, 1)
            rows.append(entry)

    # Rank drafts within their own season — league size and scoring both move.
    for season in arc.completed:
        cohort = [r for r in rows if r["season"] == season.year]
        for rank, row in enumerate(sorted(cohort, key=lambda r: -r["draft_points"]), start=1):
            row["draft_rank"] = rank
        for rank, row in enumerate(sorted(cohort, key=lambda r: -r["draft_value"]), start=1):
            row["draft_value_rank"] = rank
    return rows


def draft_dependence(arc: Archive, profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Does the draft decide it? Grouped by how well each team drafted."""
    buckets = {"top": [], "middle": [], "bottom": []}
    for row in profiles:
        third = (row["draft_value_rank"] - 1) / row["teams"]
        key = "top" if third < 1 / 3 else ("bottom" if third >= 2 / 3 else "middle")
        buckets[key].append(row)

    summary = []
    for key in ("top", "middle", "bottom"):
        rows = buckets[key]
        summary.append(
            {
                "bucket": key,
                "label": {"top": "Drafted best", "middle": "Drafted middling",
                          "bottom": "Drafted worst"}[key],
                "teams": len(rows),
                "playoff_rate": round(sum(r["made_playoffs"] for r in rows) / len(rows) * 100, 1),
                "titles": sum(r["champion"] for r in rows),
                "average_finish": round(sum(r["finish"] for r in rows) / len(rows), 1),
            }
        )

    outcome = {}
    for key, rows in (
        ("champions", [r for r in profiles if r["champion"]]),
        ("playoffs", [r for r in profiles if r["made_playoffs"]]),
        ("missed", [r for r in profiles if not r["made_playoffs"]]),
    ):
        outcome[key] = {
            "teams": len(rows),
            **{
                source: round(sum(r[source] for r in rows) / len(rows), 1)
                for source in SOURCES
            },
            "points": round(sum(r["points"] for r in rows) / len(rows), 1),
        }

    return {"buckets": summary, "by_outcome": outcome}


def comebacks(arc: Archive, profiles: list[dict[str, Any]], limit: int = 8) -> dict[str, Any]:
    """Bad drafts that still made the playoffs — and good drafts that did not."""
    overcame = [
        r for r in profiles
        if r["made_playoffs"] and (r["draft_value_rank"] - 1) / r["teams"] >= 0.5
    ]
    for row in overcame:
        row["rescued_by"] = round(row["trade_points"] + row["waiver_points"], 1)
        row["rescue_share"] = round(row["trade"] + row["waiver"], 1)
    overcame.sort(key=lambda r: -r["rescue_share"])

    wasted = [
        r for r in profiles
        if not r["made_playoffs"] and (r["draft_value_rank"] - 1) / r["teams"] < 1 / 3
    ]
    wasted.sort(key=lambda r: r["draft_rank"])

    return {
        "overcame": overcame[:limit],
        "wasted": wasted[:limit],
        "overcame_count": len(overcame),
        "playoff_seasons": sum(1 for r in profiles if r["made_playoffs"]),
    }


def draft_as_currency(profiles: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    """Managers who drafted well and then spent the picks rather than started them.

    Two different questions hide behind the phrase "a bad draft". `draft_value_rank`
    asks whether the picks were good; `draft_rank` asks how much of the season's
    scoring those picks went on to provide. A manager who drafts brilliantly and
    trades all of it away scores badly on the second while deserving nothing but
    credit on the first — so the gap between the two ranks is its own story.
    """
    out = []
    for row in profiles:
        gap = row["draft_rank"] - row["draft_value_rank"]
        if gap < 3:
            continue
        out.append({**row, "gap": gap})
    out.sort(key=lambda r: -r["gap"])
    return out[:limit]


def build(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    tagged = attribute(arc, tables["team_weeks"])
    deals = trades(arc, tagged)
    profiles = season_profiles(arc, tagged, tables)
    return {
        "channels": channel_share(arc, tagged),
        "trades": deals,
        "trade_ledger": trade_ledger(arc, deals),
        "waivers": waiver_hits(arc, tagged, tables),
        "profiles": profiles,
        "dependence": draft_dependence(arc, profiles),
        "comebacks": comebacks(arc, profiles),
        "currency": draft_as_currency(profiles),
    }
