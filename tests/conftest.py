from __future__ import annotations

import pytest

from fwffl_annual import frames
from fwffl_annual.archive import Archive


@pytest.fixture(scope="session")
def arc() -> Archive:
    """The real archive, served from the on-disk cache."""
    return Archive.load()


@pytest.fixture(scope="session")
def tables(arc: Archive) -> dict:
    return frames.build_all(arc)
