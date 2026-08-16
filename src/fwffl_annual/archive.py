"""The league archive: every season, walked back through Sleeper's chain.

A Sleeper league is a linked list — each season points at `previous_league_id`.
`Archive.load()` walks that chain from the current league back to the first, so
adding a season next year requires changing nothing.

Identity note: managers are keyed by `user_id`, never by display name or roster
id. Display names change, roster ids are reassigned between seasons, and a
manager who leaves frees their slot for someone else. `user_id` is the only
stable handle.
"""

from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from . import sleeper

# The current season's league. Every prior season is discovered from here.
LEAGUE_ID = "1389332759826173952"

MAX_WEEK = 18
FLEX_POSITIONS = frozenset({"RB", "WR", "TE"})
SCORING_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K", "DEF"})


@dataclass
class Season:
    """One season of one league, fully loaded."""

    year: str
    league_id: str
    league: dict[str, Any]
    users: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    matchups: dict[int, list[dict[str, Any]]]
    transactions: dict[int, list[dict[str, Any]]]
    winners_bracket: list[dict[str, Any]]
    losers_bracket: list[dict[str, Any]]
    draft: dict[str, Any] | None
    draft_picks: list[dict[str, Any]]
    traded_picks: list[dict[str, Any]] = field(default_factory=list)

    # --- shape -------------------------------------------------------------

    @property
    def teams(self) -> int:
        return int(self.league["total_rosters"])

    @property
    def playoff_week(self) -> int:
        return int(self.league["settings"]["playoff_week_start"])

    @property
    def scoring(self) -> dict[str, float]:
        return self.league["scoring_settings"]

    @property
    def starting_slots(self) -> list[str]:
        return [p for p in self.league["roster_positions"] if p not in ("BN", "IR", "TAXI")]

    @property
    def uses_median_match(self) -> bool:
        """Since 2022 each team also plays the league median every week."""
        return bool(self.league["settings"].get("league_average_match"))

    @property
    def complete(self) -> bool:
        return self.league["status"] == "complete"

    @property
    def regular_weeks(self) -> range:
        return range(1, self.playoff_week)

    # --- identity ----------------------------------------------------------

    @cached_property
    def owner_of(self) -> dict[int, str | None]:
        """roster_id -> user_id (None when a roster is unclaimed)."""
        return {r["roster_id"]: r.get("owner_id") for r in self.rosters}

    @cached_property
    def roster_of(self) -> dict[str, int]:
        """user_id -> roster_id."""
        return {uid: rid for rid, uid in self.owner_of.items() if uid}

    @cached_property
    def team_names(self) -> dict[str, str]:
        """user_id -> the team name they used this season."""
        out = {}
        for u in self.users:
            meta = u.get("metadata") or {}
            out[u["user_id"]] = meta.get("team_name") or u["display_name"]
        return out

    @cached_property
    def nicknames(self) -> dict[str, dict[str, str]]:
        """user_id -> {player_id: nickname} from roster metadata."""
        out: dict[str, dict[str, str]] = {}
        for r in self.rosters:
            uid = r.get("owner_id")
            if not uid:
                continue
            meta = r.get("metadata") or {}
            nicks = {
                k.removeprefix("p_nick_"): v.strip()
                for k, v in meta.items()
                if k.startswith("p_nick_") and isinstance(v, str) and v.strip()
            }
            if nicks:
                out[uid] = nicks
        return out

    @cached_property
    def champion(self) -> str | None:
        """user_id of the title winner, or None if the season is unfinished."""
        final = [m for m in self.winners_bracket if m.get("p") == 1]
        if not final or not isinstance(final[0].get("w"), int):
            return None
        return self.owner_of.get(final[0]["w"])

    @cached_property
    def runner_up(self) -> str | None:
        final = [m for m in self.winners_bracket if m.get("p") == 1]
        if not final or not isinstance(final[0].get("l"), int):
            return None
        return self.owner_of.get(final[0]["l"])

    @cached_property
    def playoff_teams(self) -> set[str]:
        """user_ids that reached the winners bracket."""
        rids: set[int] = set()
        for m in self.winners_bracket:
            for slot in ("t1", "t2"):
                if isinstance(m.get(slot), int):
                    rids.add(m[slot])
        return {uid for rid in rids if (uid := self.owner_of.get(rid))}

    @cached_property
    def last_scored_week(self) -> int:
        """Last week with any real scoring. Guards against unplayed weeks."""
        for w in range(MAX_WEEK, 0, -1):
            if any((m.get("points") or 0) > 0 for m in self.matchups.get(w, [])):
                return w
        return 0


@dataclass
class Archive:
    seasons: list[Season]
    players: dict[str, Any]
    season_stats: dict[str, dict[str, Any]]

    # --- loading -----------------------------------------------------------

    @classmethod
    def load(cls, league_id: str = LEAGUE_ID) -> Archive:
        chain: list[tuple[str, dict[str, Any]]] = []
        current: str | None = league_id
        while current:
            league = sleeper.league(current)
            chain.append((current, league))
            current = league.get("previous_league_id")

        with cf.ThreadPoolExecutor(8) as pool:
            seasons = list(pool.map(lambda item: _load_season(*item), chain))
        seasons.sort(key=lambda s: s.year)

        players = sleeper.players()
        stats = {}
        for s in seasons:
            if s.complete:
                stats[s.year] = sleeper.season_stats(s.year)
        return cls(seasons=seasons, players=players, season_stats=stats)

    # --- lookups -----------------------------------------------------------

    @cached_property
    def by_year(self) -> dict[str, Season]:
        return {s.year: s for s in self.seasons}

    @cached_property
    def completed(self) -> list[Season]:
        return [s for s in self.seasons if s.complete]

    @cached_property
    def current(self) -> Season:
        return self.seasons[-1]

    @cached_property
    def manager_names(self) -> dict[str, str]:
        """user_id -> display name, with the most recent season winning."""
        out: dict[str, str] = {}
        for s in self.seasons:
            for u in s.users:
                out[u["user_id"]] = u["display_name"]
        return out

    def manager(self, uid: str | None) -> str:
        if not uid:
            return "Unclaimed"
        return self.manager_names.get(uid, uid)

    def who(self, year: str, roster_id: int | None) -> str:
        """Display name for whoever owned `roster_id` in `year`."""
        if roster_id is None:
            return "Unclaimed"
        return self.manager(self.by_year[year].owner_of.get(int(roster_id)))

    @cached_property
    def seasons_played(self) -> dict[str, list[str]]:
        """user_id -> the years they appear in."""
        out: dict[str, list[str]] = {}
        for s in self.seasons:
            for u in s.users:
                out.setdefault(u["user_id"], []).append(s.year)
        return out

    # --- players -----------------------------------------------------------

    def player_name(self, pid: str | None) -> str:
        if pid is None:
            return "—"
        p = self.players.get(str(pid))
        if not p:
            return str(pid)
        full = p.get("full_name")
        if full:
            return full
        joined = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        return joined or str(pid)

    def position(self, pid: str | None) -> str:
        p = self.players.get(str(pid)) if pid else None
        return (p or {}).get("position") or "?"

    def team(self, pid: str | None) -> str:
        p = self.players.get(str(pid)) if pid else None
        return (p or {}).get("team") or ""


def _load_season(league_id: str, league: dict[str, Any]) -> Season:
    year = league["season"]
    drafts = sleeper.drafts(league_id)
    draft_meta = sleeper.draft(drafts[0]["draft_id"]) if drafts else None
    picks: list[dict[str, Any]] = []
    for d in drafts:
        picks.extend(sleeper.draft_picks(d["draft_id"]))

    weeks = range(1, MAX_WEEK + 1)
    return Season(
        year=year,
        league_id=league_id,
        league=league,
        users=sleeper.users(league_id),
        rosters=sleeper.rosters(league_id),
        matchups={w: sleeper.matchups(league_id, w) for w in weeks},
        transactions={w: sleeper.transactions(league_id, w) for w in weeks},
        winners_bracket=sleeper.winners_bracket(league_id),
        losers_bracket=sleeper.losers_bracket(league_id),
        draft=draft_meta,
        draft_picks=picks,
        traded_picks=sleeper.traded_picks(league_id),
    )
