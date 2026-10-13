import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from airdata import regions, store  # noqa: E402
from assistant import tools  # noqa: E402


def test_airports_resolve_by_code_city_name_and_keyword(monkeypatch):
    table = pd.DataFrame({
        "name": ["John Wayne Orange County International Airport", "Orange County Airport",
                 "Los Angeles International Airport"],
        "city": ["Santa Ana", "Montgomery", "Los Angeles"],
        "keywords": ["Disneyland, Orange County", "", "LAX"],
        "passengers": [5_000_000, 1_000, 40_000_000],
    }, index=pd.Index(["SNA", "MGJ", "LAX"], name="code"))
    monkeypatch.setattr(store, "table", lambda: table)
    assert store.resolve_airport("sna") == "SNA"
    assert store.resolve_airport("Santa Ana") == "SNA"
    assert store.resolve_airport("Los Angeles airport") == "LAX"
    assert store.resolve_airport("Orange County") == "SNA"  # the largest match wins
    assert store.resolve_airport("Boston, MA") is None
    assert store.resolve_airport("anta") is None  # whole words only, not a substring of "Santa"


def test_named_regions_resolve_without_the_states_file():
    assert regions.resolve_region("New England") == regions.DIVISIONS["new england"]
    assert regions.resolve_region("Mid-Atlantic") == regions.DIVISIONS["middle atlantic"]
    assert regions.resolve_region("West Coast") == ["CA", "OR", "WA"]
    assert regions.resolve_region("US") is None


def test_every_region_resolves_to_itself():
    for region, states in regions.REGIONS.items():
        assert regions.resolve_region(region) == states


def test_regions_named_in_the_tool_description_resolve():
    description = tools.REGISTRY["rank_airports"].parameters["region"].description
    examples = re.findall(r"'([^']+)'", description)
    assert "West Coast" in examples
    for example in examples:
        regions.resolve_region(example)  # raises ValueError if the model is offered a dead name
