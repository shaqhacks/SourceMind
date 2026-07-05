"""Golden snapshot tests: outline + first-40-lines output must match the
committed snapshots exactly. If this fails after an intentional
extractor/outline-algorithm change (an extractor_version bump), regenerate
via `python scripts/make_fixtures.py --snapshots` in the SAME PR — do not
"fix" the test by hand-editing the snapshot JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.make_fixtures import FIXTURES_DIR, _SNAPSHOT_FIXTURES, _snapshot_for

SNAPSHOTS_DIR = Path(__file__).resolve().parent / "snapshots"


@pytest.mark.parametrize("name", _SNAPSHOT_FIXTURES)
def test_golden_snapshot_matches(name: str) -> None:
    expected = json.loads((SNAPSHOTS_DIR / f"{name}.json").read_text())
    actual = _snapshot_for(FIXTURES_DIR / f"{name}.pdf")
    assert actual == expected
