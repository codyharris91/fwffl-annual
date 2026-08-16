"""The load-bearing test: our scoring must reproduce Sleeper's own numbers.

Everything downstream — draft value, the best undrafted player, positional
finishes — depends on being able to score an arbitrary NFL stat line under this
league's settings. If this drifts, those numbers are quietly wrong.
"""

from __future__ import annotations

import pytest

from fwffl_annual.scoring import score, score_all


def test_scoring_matches_sleeper_for_full_season_players(arc, tables):
    """Players rostered all year should total exactly what the league recorded."""
    players = tables["player_weeks"]
    checked = 0

    for season in arc.completed:
        observed = players[players.season == season.year].groupby("pid").agg(
            points=("points", "sum"), weeks=("week", "nunique")
        )
        # Only players on a roster every single week have a complete observed total.
        full_season = observed[observed.weeks >= season.last_scored_week]
        computed = score_all(arc.season_stats[season.year], season.scoring)

        for pid, row in full_season.iterrows():
            if pid not in computed:
                continue
            assert computed[pid] == pytest.approx(row.points, abs=0.02), (
                f"{arc.player_name(pid)} in {season.year}: "
                f"computed {computed[pid]} vs league {row.points}"
            )
            checked += 1

    assert checked > 100, f"only validated {checked} players — test is not proving much"


def test_score_uses_league_signature_keys():
    """First downs and the TE bonus must actually be counted, not silently dropped."""
    settings = {"rec": 0.5, "rec_fd": 0.5, "bonus_rec_te": 0.5, "pass_td": 5.0}
    line = {"rec": 10, "rec_fd": 6, "bonus_rec_te": 10, "pass_td": 2}
    # 5 + 3 + 5 + 10
    assert score(line, settings) == pytest.approx(23.0)


def test_score_ignores_stats_the_league_does_not_score():
    assert score({"rush_att": 30}, {"rush_yd": 0.1}) == 0.0
