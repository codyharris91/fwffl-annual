"""The eight stat categories that make up the annual."""

from __future__ import annotations

from typing import Any

from ..archive import Archive
from . import coaching, comedy, draft, ledger, luck, records, rivalries, waivers

CATEGORIES = {
    "ledger": ledger,
    "luck": luck,
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
