import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from analysis import scoring  # noqa: E402

MONTHS = pd.date_range("2022-05-01", "2026-04-01", freq="MS")  # 48 months


def airport_months(code, passengers, seats, growth=0.0, departures=1000):
    """Flat monthly traffic, with passengers growing `growth` per year towards the end."""
    rows = []
    for i, month in enumerate(MONTHS):
        years_before_end = (len(MONTHS) - 1 - i) // 12
        rows.append({"code": code, "month": month,
                     "passengers": passengers / (1 + growth) ** years_before_end,
                     "seats": seats, "departures": departures, "intl_departures": 100})
    return rows


@pytest.fixture
def table():
    monthly = pd.DataFrame(
        airport_months("FUL", 90_000, 100_000, growth=0.10)      # full and growing
        + airport_months("MID", 75_000, 100_000)                 # average
        + airport_months("BIG", 700_000, 1_000_000, departures=9000)  # large, congested
        + airport_months("TNY", 1_000, 2_000))                   # below the peer threshold
    airports = pd.DataFrame({
        "name": ["Full", "Mid", "Big", "Tiny"], "city": ["A", "B", "C", "D"],
        "state": ["MA", "MA", "CA", "VT"], "runways": [2, 2, 2, 1],
    }, index=pd.Index(["FUL", "MID", "BIG", "TNY"], name="code"))
    ontime = pd.DataFrame({
        "scheduled_flights": [1000, 1000, 9000], "long_haul_flights": [100, 0, 2700],
        "pct_delayed_15": [10.0, 15.0, 30.0], "avg_taxi_out_min": [12.0, 14.0, 25.0],
    }, index=pd.Index(["FUL", "MID", "BIG"], name="code"))
    return scoring.build_table(monthly, airports, ontime)


def test_peer_set_drops_small_airports(table):
    assert set(table.index) == {"FUL", "MID", "BIG"}


def test_load_factor(table):
    assert table.loc["FUL", "load_factor"] == pytest.approx(90.0)
    assert table.loc["MID", "load_factor"] == pytest.approx(75.0)


def test_unmet_demand_counts_only_passengers_above_comfort_level(table):
    # 90k passengers on 100k seats: 10k above the 80% level each month, 12 months.
    assert table.loc["FUL", "excess_passengers"] == pytest.approx(120_000)
    assert table.loc["MID", "excess_passengers"] == 0


def test_unmet_demand_is_a_share_of_passengers_not_a_size_ranking(table):
    # FUL carries 1.08M a year, 120k of it above the comfort level; BIG is 8x larger.
    assert table.loc["FUL", "unmet_demand"] == pytest.approx(120_000 / 1_080_000 * 100)
    assert table.loc["FUL", "unmet_demand"] > table.loc["BIG", "unmet_demand"]


def test_passenger_growth_is_annualised(table):
    assert table.loc["FUL", "passenger_growth"] == pytest.approx(10.0)
    assert table.loc["MID", "passenger_growth"] == pytest.approx(0.0)


def test_long_haul_share(table):
    assert table.loc["BIG", "pct_long_haul"] == pytest.approx(30.0)
    assert table.loc["MID", "pct_long_haul"] == 0


def test_congestion_orders_airports(table):
    assert table["congestion"].idxmax() == "BIG"
    assert table.loc["BIG", "congestion"] == pytest.approx(100.0)


def test_expansion_score_is_the_weighted_sum_of_its_components(table):
    w = config.EXPANSION_WEIGHTS
    assert sum(w.values()) == pytest.approx(1.0)
    for code, row in table.iterrows():
        expected = sum(w[k] * row[f"rank_{k}"] for k in w)
        assert row["expansion_score"] == pytest.approx(expected)
    assert table["expansion_score"].between(0, 100).all()


def test_full_growing_airport_beats_average_one(table):
    assert table.loc["FUL", "expansion_score"] > table.loc["MID", "expansion_score"]


def test_rank_range_brackets_the_configured_rank(table):
    assert (table["expansion_rank_best"] <= table["expansion_rank"]).all()
    assert (table["expansion_rank"] <= table["expansion_rank_worst"]).all()
    assert table.loc[table["expansion_score"].idxmax(), "expansion_rank"] == 1


def test_drivers_say_whether_the_rank_depends_on_the_weights(table):
    row = table.loc["FUL"].copy()
    row[["expansion_rank", "expansion_rank_best", "expansion_rank_worst"]] = [4, 4, 5]
    assert "robust to the weights" in " ".join(scoring.drivers(row))
    row["expansion_rank_worst"] = config.ROBUST_TOP_N + 40  # wide spread and out of the top
    assert "depends on the weights" in " ".join(scoring.drivers(row))


def test_drivers_flag_missing_data_instead_of_hiding_it(table):
    row = table.loc["FUL"].copy()
    row[["pct_delayed_15", "passenger_growth"]] = float("nan")
    text = " ".join(scoring.drivers(row))
    assert "No on-time data" in text and "median airport" in text


def test_sensitivity_weights_with_wrong_keys_are_rejected(monkeypatch):
    monkeypatch.setitem(config.SENSITIVITY_WEIGHTS, "broken", {"volume": 1.0})
    with pytest.raises(ValueError, match="SENSITIVITY_WEIGHTS"):
        scoring.build_table(*_inputs())


def _inputs():
    from test_metrics import _inputs as inputs
    return inputs()


def test_drivers_explain_a_full_airport(table):
    text = " ".join(scoring.drivers(table.loc["FUL"]))
    assert "Flights are full" in text and "Fast growth" in text
