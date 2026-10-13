"""The metrics a user can ask about, one registry entry each.

Adding a metric means adding one `Metric` here (plus its column in scoring.build_table):
the tool enum, the prompt, the page labels, the caveats and the explain breakdown all
derive from this registry.
"""
from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

import config
from analysis import scoring


def clean(value):
    """A number as shown to the user: None when missing, whole when large, else 1 decimal."""
    if pd.isna(value):
        return None
    value = float(value)
    return round(value) if abs(value) >= 1000 else round(value, 1)


@dataclass(frozen=True)
class Metric:
    """One metric the agent can rank or explain."""
    id: str                   # column name in the scored table
    label: str                # shown to the user and to the model
    caveats: tuple = ()       # assumptions to state whenever the metric is used
    components: Optional[Callable[[pd.Series], list]] = None  # explain breakdown; default is the value alone
    reasons_apply: bool = True   # whether scoring.drivers() explains this metric
    live_status: bool = False    # whether explaining it adds the live FAA status

    def breakdown(self, row: pd.Series) -> list:
        """The parts of this metric for one airport's row of the scored table."""
        if self.components:
            return self.components(row)
        return [{"component": self.label, "value": clean(row[self.id])}]


def _expansion_parts(r):
    return [{"component": label,
             "percentile_rank": clean(r[scoring.rank_column(key)]),
             "weight": config.EXPANSION_WEIGHTS[key],
             "points": clean(r[scoring.rank_column(key)] * config.EXPANSION_WEIGHTS[key])}
            for key, label in scoring.EXPANSION_COMPONENTS.items()]


def _congestion_parts(r):
    parts = [{"component": label, "value": clean(r[column]),
              "percentile_rank": clean(r[scoring.rank_column(column)])}
             for column, label in scoring.CONGESTION_INPUTS.items()]
    parts[-1]["component"] += f" ({int(r['runways'])} runways)"
    return parts


def _unmet_demand_parts(r):
    return [
        {"component": "passengers above comfort load factor, per year",
         "value": clean(r["excess_passengers"])},
        {"component": "as % of passengers carried (the unmet demand proxy)",
         "value": clean(r["unmet_demand"])},
        {"component": "load factor (%)", "value": clean(r["load_factor"])},
        {"component": "passenger growth, last year (%)", "value": clean(r["passenger_growth_1y"])},
        {"component": "seat growth, last year (%)", "value": clean(r["seat_growth_1y"])},
        {"component": "peak month vs average month", "value": clean(r["peak_month_ratio"])},
    ]


def _long_haul_parts(r):
    return [
        {"component": "scheduled domestic departures in the month",
         "value": clean(r["scheduled_flights"])},
        {"component": f"of which {config.LONG_HAUL_MILES:,}+ miles",
         "value": clean(r["long_haul_flights"])},
        {"component": "long-haul share of domestic departures (%)",
         "value": clean(r["pct_long_haul"])},
        {"component": "international share of all departures (%)",
         "value": clean(r["pct_international"])},
    ]


# Order matters: it is the order of the tool enum, the prompt, and the page's labels.
_REGISTRY = [
    Metric("expansion_score", "Expansion opportunity score (0-100)",
           caveats=(
               "Weights are a judgement call: " + ", ".join(
                   f"{scoring.EXPANSION_COMPONENTS[k]} {w:.0%}"
                   for k, w in config.EXPANSION_WEIGHTS.items()) + ".",
               "No cost or revenue data is used, so the score measures capacity pressure, "
               "growth and scale, not return on investment."),
           components=_expansion_parts),
    Metric("congestion", "Congestion index (0-100)",
           caveats=(
               f"Delay and taxi-out figures cover domestic flights of large US carriers for "
               f"one month ({config.ONTIME_PERIOD}), so weather that month matters.",
               "Runway count is a crude measure of airfield capacity (ignores layout, gates, "
               "slots)."),
           components=_congestion_parts, live_status=True),
    Metric("unmet_demand",
           f"Unmet demand proxy (% of passengers above {config.COMFORT_LOAD_FACTOR:.0f}% "
           "load factor)",
           caveats=(
               f"Proxy only: the share of passengers carried above an "
               f"{config.COMFORT_LOAD_FACTOR:.0f}% load factor, so airports are compared "
               "independent of size. Demand that was actually turned away is not published.",),
           components=_unmet_demand_parts),
    Metric("pct_long_haul", "Long-haul share of domestic departures (%)",
           caveats=(
               f"Long-haul = {config.LONG_HAUL_MILES:,} miles or more. Counted over domestic "
               f"flights of large US carriers in {config.ONTIME_PERIOD}; international "
               "flights are shown as a separate share because their distances are not in "
               "the data.",),
           components=_long_haul_parts,
           reasons_apply=False),  # demand/capacity reasons do not explain a route-mix figure
    Metric("load_factor", "Load factor (%)"),
    Metric("passenger_growth",
           f"Passenger growth per year over {config.GROWTH_YEARS} years (%)"),
    Metric("passengers", "Passengers, last 12 months"),
]

METRICS = {m.id: m for m in _REGISTRY}
LABELS = {m.id: m.label for m in _REGISTRY}
