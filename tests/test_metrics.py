import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from analysis import metrics, scoring  # noqa: E402
from assistant import tools  # noqa: E402
from test_scoring import table  # noqa: E402,F401  (fixture)


def test_every_summary_column_is_a_registered_metric():
    assert set(tools.SUMMARY_COLUMNS) == set(metrics.METRICS)


def test_expansion_components_match_the_configured_weights():
    assert set(scoring.EXPANSION_COMPONENTS) == set(config.EXPANSION_WEIGHTS)


def test_every_metric_can_be_explained(table):  # noqa: F811
    row = table.loc["FUL"].copy()
    row["runways"] = 2  # the scored table keeps it; ontime-less rows are not under test
    for spec in metrics.METRICS.values():
        parts = spec.breakdown(row)
        assert parts and all("component" in part for part in parts)


def test_weight_without_a_matching_component_is_rejected(monkeypatch, table):  # noqa: F811
    monkeypatch.setitem(config.EXPANSION_WEIGHTS, "ticket_price", 0.1)
    with pytest.raises(ValueError, match="EXPANSION_WEIGHTS"):
        scoring.build_table(*_inputs())


def _inputs():
    import pandas as pd
    from test_scoring import airport_months
    monthly = pd.DataFrame(airport_months("FUL", 90_000, 100_000))
    airports = pd.DataFrame({"name": ["Full"], "city": ["A"], "state": ["MA"], "runways": [2]},
                            index=pd.Index(["FUL"], name="code"))
    ontime = pd.DataFrame({"scheduled_flights": [1000], "long_haul_flights": [100],
                           "pct_delayed_15": [10.0], "avg_taxi_out_min": [12.0]},
                          index=pd.Index(["FUL"], name="code"))
    return monthly, airports, ontime
