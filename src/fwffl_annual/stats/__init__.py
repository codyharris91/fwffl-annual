"""The stat categories that make up the annual and the roster-building page."""

from __future__ import annotations

from typing import Any

from ..archive import Archive
from . import (
    acquisition, coaching, comedy, draft, ledger, luck, median, records, rivalries, waivers,
)

CATEGORIES = {
    "ledger": ledger,
    "acquisition": acquisition,
    "luck": luck,
    "median": median,
    "records": records,
    "coaching": coaching,
    "draft": draft,
    "waivers": waivers,
    "rivalries": rivalries,
    "comedy": comedy,
}


def build_all(arc: Archive, tables: dict[str, Any]) -> dict[str, Any]:
    return {name: module.build(arc, tables) for name, module in CATEGORIES.items()}


__all__ = ["CATEGORIES", "build_all"]
