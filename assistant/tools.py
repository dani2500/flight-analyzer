"""The three tools the agent can call. Each returns plain JSON-able dicts holding every
number shown to the user, plus the assumptions behind them. Usable without any LLM:

    python -c "from assistant import tools; import json; print(json.dumps(tools.rank_airports('New England'), indent=1))"
"""
from dataclasses import dataclass
from typing import Callable, Optional, TypedDict

import pandas as pd

import config
from airdata import faa, regions, store
from analysis import metrics, scoring

# Metric columns of every result row, in the order the page shows them.
SUMMARY_COLUMNS = ["expansion_score", "congestion", "load_factor", "passenger_growth",
                   "unmet_demand", "pct_long_haul", "passengers"]

GENERAL = [f"Peer set: US airports with at least {config.MIN_ANNUAL_PASSENGERS:,} passengers "
           "a year. Scores are percentile ranks within that set.",
           "Traffic figures are BTS T-100 and lag about 5 months."]


class ToolResult(TypedDict, total=False):
    """What every tool returns. This is the contract with the page (static/app.js) and,
    for "reasons", "breakdown", "head_to_head" and "error", with the system prompt."""
    error: str                          # set instead of everything else when the tool failed
    title: str
    rows: list                          # one dict per airport: code, airport, city, metrics
    ranked_by: str
    rank: str                           # explain_metric: "3 of 120"
    breakdown: list                     # explain_metric: the parts of the metric
    reasons: dict                       # airport code -> rule-based reasons
    head_to_head: list                  # compare_airports: who is higher on each metric
    live_faa_status: dict               # airport code -> events, or a "none" sentence
    not_found: list                     # compare_airports: names that did not resolve
    data_period: str
    assumptions: list


def error(message: str) -> ToolResult:
    """The result of a tool that could not answer; the model relays the message."""
    return {"error": message}


def _row(code, row, extra=()):
    out = {"code": code, "airport": row["name"], "city": f"{row['city']}, {row['state']}"}
    out.update({c: metrics.clean(row[c]) for c in [*SUMMARY_COLUMNS, *extra]})
    return out


def _wrap(title, rows, metric_ids, **extra) -> ToolResult:
    t = store.table()
    caveats = [c for m in dict.fromkeys(metric_ids) for c in metrics.METRICS[m].caveats]
    return {"title": title, "rows": rows, **extra,
            "data_period": f"T-100: {t.attrs['t100_period']}; on-time: {config.ONTIME_PERIOD}",
            "assumptions": GENERAL + caveats}


def _unknown_metric(metric):
    return error(f"Unknown metric '{metric}'. Choose from: {', '.join(metrics.METRICS)}")


def _live_status(code):
    return {code: faa.faa_status(code) or "No FAA delay programme right now."}


def _clamp_top_n(top_n) -> int:
    """How many airports to return: the default for junk, otherwise 1 to MAX_TOP_N.

    The model may send a string, zero or a negative number; pandas would treat -3 as
    "all but the last three".
    """
    try:
        n = int(top_n)
    except (TypeError, ValueError):
        return config.DEFAULT_TOP_N
    return min(max(n, 1), config.MAX_TOP_N)


def rank_airports(region=None, metric="expansion_score", top_n=config.DEFAULT_TOP_N):
    """Rank airports in a region (or the whole US) by one metric, highest first."""
    if metric not in metrics.METRICS:
        return _unknown_metric(metric)
    try:
        states = regions.resolve_region(region)
    except ValueError as e:
        return error(str(e))
    t = store.table()
    pool = t if states is None else t[t["state"].isin(states)]
    if pool.empty:
        return error(f"No airport in {region} has at least {config.MIN_ANNUAL_PASSENGERS:,} "
                     "passengers a year, so there is nothing to rank.")
    top = pool.sort_values(metric, ascending=False).head(_clamp_top_n(top_n))
    rows = [_row(code, row) for code, row in top.iterrows()]
    return _wrap(f"Top {len(rows)} of {len(pool)} airports in {region or 'the US'} "
                 f"by {metrics.LABELS[metric]}", rows, (metric, "expansion_score"),
                 ranked_by=metric,
                 reasons={code: scoring.drivers(row) for code, row in top.iterrows()})


def compare_airports(airports):
    """Side-by-side profile of one or more airports, with live FAA status."""
    if isinstance(airports, str):
        airports = [airports]
    t = store.table()
    rows, reasons, live, unknown = [], {}, {}, []
    for name in airports:
        code = store.resolve_airport(name)
        if code is None:
            unknown.append(name)
            continue
        rows.append(_row(code, t.loc[code], extra=scoring.CONGESTION_INPUTS))
        reasons[code] = scoring.drivers(t.loc[code])
        live.update(_live_status(code))
    if not rows:
        return error(f"Could not find a US commercial airport for: {', '.join(unknown)}")
    # Spell out who is higher on each metric, so the model does not have to read it off the table.
    labels = {**metrics.LABELS, **scoring.CONGESTION_INPUTS}
    head_to_head = [
        f"{labels[m]}: " + " > ".join(f"{r['code']} {r[m]:,}" for r in
                                      sorted(rows, key=lambda r: r[m], reverse=True))
        for m in ["congestion", *scoring.CONGESTION_INPUTS, "expansion_score", "unmet_demand"]
        if len(rows) > 1 and all(r[m] is not None for r in rows)]
    out = _wrap("Comparison: " + " vs ".join(r["code"] for r in rows), rows, metrics.METRICS,
                head_to_head=head_to_head, reasons=reasons, live_faa_status=live)
    if unknown:
        out["not_found"] = unknown
    return out


def explain_metric(airport, metric="expansion_score"):
    """Break one metric for one airport into its components, with its rank among peers."""
    spec = metrics.METRICS.get(metric)
    if spec is None:
        return _unknown_metric(metric)
    code = store.resolve_airport(airport)
    if code is None:
        return error(f"Could not find a US commercial airport for '{airport}'.")
    t = store.table()
    r = t.loc[code]
    rank = int(t[metric].rank(ascending=False, method="min")[code]) if pd.notna(r[metric]) else None

    extra = {"live_faa_status": _live_status(code)} if spec.live_status else {}
    return _wrap(f"{code} ({r['name']}): {spec.label} = {metrics.clean(r[metric])}",
                 [_row(code, r)], (metric,), breakdown=spec.breakdown(r),
                 rank=f"{rank} of {len(t)}" if rank else "not available",
                 reasons={code: scoring.drivers(r)} if spec.reasons_apply else {},
                 **extra)


@dataclass(frozen=True)
class Param:
    """One argument of a tool, as the model sees it."""
    type: str
    description: str = ""
    enum: Optional[list] = None
    items: Optional[dict] = None   # element type, for arrays
    required: bool = True

    def schema(self) -> dict:
        out = {"type": self.type}
        if self.description:
            out["description"] = self.description
        if self.enum:
            out["enum"] = self.enum
        if self.items:
            out["items"] = self.items
        return out


@dataclass(frozen=True)
class Tool:
    """A function the model may call: what it is for, its arguments, and the code to run."""
    name: str
    description: str
    parameters: dict   # argument name -> Param
    run: Callable

    def schema(self) -> dict:
        """The definition in the format Ollama's chat API expects."""
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {k: p.schema() for k, p in self.parameters.items()},
                "required": [k for k, p in self.parameters.items() if p.required]}}}


_METRIC = Param("string", enum=list(metrics.METRICS))

TOOLS = [
    Tool("rank_airports",
         "Rank US airports in a region by one metric, highest first. "
         "Use for 'which airports...', 'top...', 'best candidates...'.",
         {"region": Param("string", "US state name or code, a region such as 'New England', "
                                    "'Midwest', 'West Coast', or 'US' for all."),
          "metric": _METRIC,
          "top_n": Param("integer", f"How many airports, 1 to {config.MAX_TOP_N}, "
                                    f"default {config.DEFAULT_TOP_N}.",
                         required=False)},
         rank_airports),
    Tool("compare_airports",
         "All metrics side by side for one or more named airports, with live FAA delay "
         "status. Use for 'compare A and B' or 'tell me about A'.",
         {"airports": Param("array", "IATA codes or city names, e.g. ['LAX', 'Santa Ana'].",
                            items={"type": "string"})},
         compare_airports),
    Tool("explain_metric",
         "Break one metric for one airport into its components and reasons. "
         "Use for 'what is the <metric> at A', 'why', 'how is it calculated'.",
         {"airport": Param("string", "IATA code or city name."),
          "metric": _METRIC},
         explain_metric),
]
REGISTRY = {tool.name: tool for tool in TOOLS}
