"""Deterministic scoring. Pure functions over DataFrames: no I/O, no LLM.

Assumptions and weights are in config.py.
"""
import pandas as pd

import config

# Display name of each expansion-score component. Its keys must match
# config.EXPANSION_WEIGHTS; build_table checks that, so a weight cannot be added or
# removed in one place only.
EXPANSION_COMPONENTS = {
    "load_factor": "load factor",
    "passenger_growth": "passenger growth",
    "volume": "volume",
    "airfield_headroom": "airfield headroom",
}

# The raw inputs of the congestion index, shown when airports are compared. Each one's
# percentile rank is stored in the table as rank_<input>.
CONGESTION_INPUTS = {
    "pct_delayed_15": "Departures delayed 15+ min (%)",
    "avg_taxi_out_min": "Average taxi-out (min)",
    "departures_per_runway_day": "Departures per runway per day",
}


def rank_column(name: str) -> str:
    """Name of the table column that holds the percentile rank of `name`.

    Args:
        name: A congestion input or an expansion-score component.

    Returns:
        The column name, e.g. "rank_load_factor".
    """
    return f"rank_{name}"


def period_label(monthly: pd.DataFrame) -> str:
    """The 12-month period the table covers, e.g. 'Jan 2025 - Dec 2025'.

    Args:
        monthly: Monthly traffic per airport, with a datetime "month" column.

    Returns:
        The first and last month of the latest 12 months, as text.
    """
    last = monthly["month"].max()
    first = last - pd.DateOffset(months=config.WINDOW_MONTHS - 1)
    return f"{first:%b %Y} - {last:%b %Y}"


def percentile(series: pd.Series) -> pd.Series:
    """Rank within the peer set, 0-100. Missing values stay missing.

    Args:
        series: One value per airport.

    Returns:
        The percentile rank of each airport, on the same index.
    """
    return series.rank(pct=True) * 100


def _window(monthly: pd.DataFrame, end: pd.Timestamp,
            months: int = config.WINDOW_MONTHS) -> pd.DataFrame:
    """The rows of `monthly` in the `months` months that end at `end`, inclusive.

    Args:
        monthly: Monthly traffic per airport, with a datetime "month" column.
        end: The last month of the window.
        months: The length of the window in months.

    Returns:
        The matching rows of `monthly`.
    """
    start = end - pd.DateOffset(months=months - 1)
    return monthly[(monthly["month"] >= start) & (monthly["month"] <= end)]


def excess_passengers(passengers: pd.Series, seats: pd.Series) -> pd.Series:
    """Passengers carried above the comfort load factor in each month.

    A month at 86% load factor with 100,000 seats counts 6,000: the demand that only
    fitted because flights ran fuller than is comfortable, a proxy for demand turned away.
    Summed over 12 months this is the unmet-demand proxy.

    Args:
        passengers: Passengers carried, one value per airport and month.
        seats: Seats offered, on the same index as `passengers`.

    Returns:
        The passengers above the comfort load factor, never below zero.
    """
    return (passengers - seats * config.COMFORT_LOAD_FACTOR / 100).clip(lower=0)


def build_table(monthly: pd.DataFrame, airports: pd.DataFrame,
                ontime: pd.DataFrame) -> pd.DataFrame:
    """One row per peer-set airport with raw inputs, component ranks and scores.

    Args:
        monthly: Monthly passengers, seats and departures per airport, with "code" and
            datetime "month" columns, covering at least the growth period.
        airports: Name, city, state, keywords and runway count, indexed by airport code.
        ontime: One-month on-time summary (delays, taxi-out, long-haul flights), indexed by
            airport code.

    Returns:
        The scored table indexed by airport code, sorted by expansion_score, highest first.
        Airports below the minimum annual passenger count are left out.
    """
    last = monthly["month"].max()
    now = _window(monthly, last)
    prev = _window(monthly, last - pd.DateOffset(years=1))
    base = _window(monthly, last - pd.DateOffset(years=config.GROWTH_YEARS))

    t = now.groupby("code")[["passengers", "seats", "departures", "intl_departures"]].sum()
    t = t.join(airports, how="inner")
    t = t[t["passengers"] >= config.MIN_ANNUAL_PASSENGERS].copy()

    t["load_factor"] = t["passengers"] / t["seats"] * 100
    # Growth needs a full base year: a part-year base (service that started later) would
    # make the airport look like it grew explosively.
    base_by_code = base.groupby("code")["passengers"]
    base_pax = base_by_code.sum().where(base_by_code.count() >= config.WINDOW_MONTHS).reindex(t.index)
    t["passenger_growth"] = ((t["passengers"] / base_pax) ** (1 / config.GROWTH_YEARS) - 1) * 100
    prev_sum = prev.groupby("code")[["passengers", "seats"]].sum().reindex(t.index)
    t["passenger_growth_1y"] = (t["passengers"] / prev_sum["passengers"] - 1) * 100
    t["seat_growth_1y"] = (t["seats"] / prev_sum["seats"] - 1) * 100
    excess = excess_passengers(now["passengers"], now["seats"])
    t["excess_passengers"] = excess.groupby(now["code"]).sum().reindex(t.index)
    # As a share of traffic, so the figure is not just a ranking of airport size.
    t["unmet_demand"] = t["excess_passengers"] / t["passengers"] * 100
    by_code = now.groupby("code")
    t["peak_month_ratio"] = (by_code["passengers"].max() / by_code["passengers"].mean()).reindex(t.index)
    t["pct_international"] = t["intl_departures"] / t["departures"] * 100
    t["departures_per_runway_day"] = t["departures"] / config.DAYS_PER_YEAR / t["runways"]

    t = t.join(ontime)
    t["pct_long_haul"] = t["long_haul_flights"] / t["scheduled_flights"] * 100

    # Congestion: mean of the available component ranks.
    for column in CONGESTION_INPUTS:
        t[rank_column(column)] = percentile(t[column])
    t["congestion"] = t[[rank_column(c) for c in CONGESTION_INPUTS]].mean(axis=1)

    # Expansion score: weighted percentile ranks. Unknown growth is treated as median.
    ranks = {
        "load_factor": percentile(t["load_factor"]),
        "passenger_growth": percentile(t["passenger_growth"]).fillna(config.UNKNOWN_GROWTH_RANK),
        "volume": percentile(t["passengers"]),
        "airfield_headroom": 100 - t["congestion"],
    }
    weights = config.EXPANSION_WEIGHTS
    if not set(ranks) == set(weights) == set(EXPANSION_COMPONENTS):
        raise ValueError(f"config.EXPANSION_WEIGHTS {sorted(weights)} must match the "
                         f"components {sorted(ranks)} that build_table ranks")
    for scenario, alt in config.SENSITIVITY_WEIGHTS.items():
        if set(alt) != set(ranks):
            raise ValueError(f"config.SENSITIVITY_WEIGHTS['{scenario}'] must have the keys "
                             f"{sorted(ranks)}")
    for name, rank in ranks.items():
        t[rank_column(name)] = rank

    def score(w):
        return sum(w[name] * rank for name, rank in ranks.items())

    t["expansion_score"] = score(weights)
    # Where each airport lands if the weights were chosen differently.
    positions = pd.DataFrame({
        "configured": t["expansion_score"],
        **{scenario: score(alt) for scenario, alt in config.SENSITIVITY_WEIGHTS.items()},
    }).rank(ascending=False, method="min")
    t["expansion_rank"] = positions["configured"]
    t["expansion_rank_best"] = positions.min(axis=1)
    t["expansion_rank_worst"] = positions.max(axis=1)
    return t.sort_values("expansion_score", ascending=False)


def drivers(row: pd.Series) -> list[str]:
    """Rule-based reasons behind an airport's numbers. This is the 'why', not the LLM.

    Args:
        row: One airport's row of the scored table (see build_table).

    Returns:
        Plain-language reasons, one sentence each. Empty only if no rule applies.
    """
    out = []
    if pd.notna(row["pct_delayed_15"]):
        out.append(f"Congestion index {row['congestion']:.0f}/100: {row['pct_delayed_15']:.1f}% "
                   f"of departures leave 15+ min late, {row['avg_taxi_out_min']:.1f} min average "
                   f"taxi-out, {row['departures_per_runway_day']:.0f} departures per runway per day.")
    else:
        out.append("No on-time data for this airport (no flights by the carriers that report "
                   "it), so the congestion index uses runway use alone. Treat it with caution.")
    if row["load_factor"] >= config.COMFORT_LOAD_FACTOR:
        out.append(f"Flights are full: {row['load_factor']:.1f}% load factor over the year, "
                   f"above the {config.COMFORT_LOAD_FACTOR:.0f}% comfort level.")
    else:
        out.append(f"Flights have spare seats on average ({row['load_factor']:.1f}% load factor), "
                   "so unmet demand is limited to peak months.")
    gap = row["passenger_growth_1y"] - row["seat_growth_1y"]
    if pd.notna(gap) and gap > config.GROWTH_GAP_POINTS:
        out.append(f"Demand is outgrowing supply: passengers {row['passenger_growth_1y']:+.1f}% "
                   f"vs seats {row['seat_growth_1y']:+.1f}% in the last year.")
    elif pd.notna(gap) and gap < -config.GROWTH_GAP_POINTS:
        out.append(f"Supply is ahead of demand: seats {row['seat_growth_1y']:+.1f}% "
                   f"vs passengers {row['passenger_growth_1y']:+.1f}% in the last year.")
    if row["congestion"] >= config.CONGESTED_INDEX:
        out.append(f"The airfield is congested (index {row['congestion']:.0f}/100), which limits "
                   "adding flights; more capacity needs airfield work, not only a terminal.")
    elif row["congestion"] <= config.HEADROOM_INDEX:
        out.append(f"The airfield has headroom (congestion index {row['congestion']:.0f}/100), "
                   "so extra terminal capacity can be turned into extra flights.")
    if row["peak_month_ratio"] >= config.SEASONAL_PEAK_RATIO:
        out.append(f"Strongly seasonal: the peak month carries {row['peak_month_ratio']:.2f}x "
                   "the average month, so pressure is concentrated in a few months.")
    if pd.isna(row["passenger_growth"]):
        out.append(f"No {config.GROWTH_YEARS}-year traffic history, so its growth is scored as "
                   "the median airport.")
    elif row["passenger_growth"] >= config.FAST_GROWTH_PCT:
        out.append(f"Fast growth: passengers up {row['passenger_growth']:.1f}% per year over "
                   f"the last {config.GROWTH_YEARS} years.")
    out.append(_rank_robustness(row))
    return out


def _rank_robustness(row: pd.Series) -> str:
    """One sentence on whether the expansion rank survives a different choice of weights."""
    tested = ", ".join(["configured", *config.SENSITIVITY_WEIGHTS])
    rank, best, worst = (int(row[c]) for c in
                         ("expansion_rank", "expansion_rank_best", "expansion_rank_worst"))
    if worst - best <= config.RANK_STABLE_SPREAD or worst <= config.ROBUST_TOP_N:
        return (f"The expansion rank is robust to the weights: #{rank} nationally, and between "
                f"#{best} and #{worst} under all weightings tested ({tested}).")
    return (f"The expansion rank depends on the weights: #{rank} as configured, but anywhere "
            f"from #{best} to #{worst} across the weightings tested ({tested}).")
