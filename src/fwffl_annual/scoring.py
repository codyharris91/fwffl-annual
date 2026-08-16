"""Stat line + league scoring settings -> fantasy points. Pure, no I/O.

Sleeper uses the same key vocabulary for stats and for scoring settings, so
scoring is a dot product over their intersection. Verified against Sleeper's own
weekly numbers for the 2025 season: exact to the cent for every player rostered
all year (see tests/test_scoring.py).

This league diverges from a public half-PPR board in ways that matter a lot:
first downs score, TEs get a reception bonus, and passing TDs are worth 5.
"""

from __future__ import annotations

from collections.abc import Mapping

# Keys that make FWFFL scoring different from a stock half-PPR league. Used for
# explaining why a player's value here differs from a public ranking.
SIGNATURE_KEYS: tuple[str, ...] = (
    "rec_fd",
    "rush_fd",
    "bonus_rec_te",
    "pass_td",
    "rec_40p",
    "rush_40p",
)


def score(stats: Mapping[str, float], settings: Mapping[str, float]) -> float:
    """Fantasy points for one stat line under one scoring config."""
    total = 0.0
    for key, weight in settings.items():
        value = stats.get(key)
        if value:
            total += value * weight
    return total


def score_all(
    stats_by_player: Mapping[str, Mapping[str, float] | None],
    settings: Mapping[str, float],
) -> dict[str, float]:
    """Score every player in a season stats payload."""
    return {
        pid: round(score(line, settings), 2)
        for pid, line in stats_by_player.items()
        if line
    }
