"""Assemble the whole annual into one JSON payload.

`python -m fwffl_annual.build` writes `data/annual.json`, which the renderer
turns into the page. Splitting the two means the numbers can be inspected,
diffed, and tested without going anywhere near HTML.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import frames, stats
from .archive import Archive
from .scoring import SIGNATURE_KEYS

OUTPUT = Path(__file__).resolve().parents[2] / "data" / "annual.json"


def meta(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    """League facts and dataset size — the page's opening credits."""
    current = arc.current
    scoring = current.scoring
    return {
        "league_name": current.league["name"],
        "league_id": current.league_id,
        "current_season": current.year,
        "current_status": current.league["status"],
        "seasons": [s.year for s in arc.seasons],
        "completed_seasons": [s.year for s in arc.completed],
        "team_counts": {s.year: s.teams for s in arc.seasons},
        "managers_all_time": len(arc.manager_names),
        "roster_slots": current.starting_slots,
        "bench_slots": len(current.league["roster_positions"]) - len(current.starting_slots),
        "playoff_teams": current.league["settings"].get("playoff_teams"),
        "playoff_week": current.playoff_week,
        "faab_budget": current.league["settings"].get("waiver_budget"),
        "median_match": current.uses_median_match,
        "scoring": {
            "ppr": scoring.get("rec"),
            "te_bonus": scoring.get("bonus_rec_te"),
            "pass_td": scoring.get("pass_td"),
            "rec_first_down": scoring.get("rec_fd"),
            "rush_first_down": scoring.get("rush_fd"),
            "signature_keys": list(SIGNATURE_KEYS),
        },
        "dataset": {
            "team_weeks": int(len(tables["team_weeks"])),
            "player_weeks": int(len(tables["player_weeks"])),
            "draft_picks": int(len(tables["picks"])),
            "transactions": int(len(tables["moves"])),
        },
    }


def build(arc: Archive | None = None) -> dict[str, Any]:
    arc = arc or Archive.load()
    tables = frames.build_all(arc)
    return {"meta": meta(arc, tables), **stats.build_all(arc, tables)}


def main() -> None:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, default=str))
    counts = payload["meta"]["dataset"]
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB)")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
