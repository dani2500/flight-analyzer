"""The scored airport table and airport lookup, built from the local files.

Downloading lives in sources.py, region names in regions.py, live FAA status in faa.py.
`python -m airdata --force` re-downloads every dataset; the server does the same for
missing ones at start, through prepare().
"""
import re
from functools import lru_cache

import pandas as pd

import config
from airdata import regions, sources
from analysis import scoring


def prepare(force=False):
    """Download whatever is missing (or everything, with force), then drop cached reads.

    Args:
        force: Re-download every dataset, even if its file already exists.

    Returns:
        The same dict as sources.status(), after the downloads.
    """
    result = sources.download(force)
    table.cache_clear()
    regions.states.cache_clear()
    return result


@lru_cache(maxsize=1)
def table():
    """The scored peer-set table (one row per airport), built from the local files."""
    if not sources.ready():
        raise RuntimeError("Data is not downloaded yet. Start the app with `python app.py` "
                           "or run `python -m airdata`.")
    monthly = pd.read_csv(config.T100_CSV, parse_dates=["month"])
    airports = pd.read_csv(config.AIRPORTS_CSV, index_col="code", keep_default_na=False)
    ontime = pd.read_csv(config.ONTIME_CSV, index_col="code")
    scored = scoring.build_table(monthly, airports, ontime)
    scored.attrs["t100_period"] = scoring.period_label(monthly)
    return scored


def resolve_airport(text):
    """'SFO', 'Santa Ana', 'Anchorage airport', 'Orange County' -> IATA code, or None.

    Nicknames ('LA') are the model's job: it is asked for IATA codes. This only validates
    codes and matches whole words against city, airport name and OurAirports keywords.

    Args:
        text: An IATA code, city name, airport name or keyword, as typed by the user.

    Returns:
        The IATA code of the best match (the largest airport that matches), or None.
    """
    t = table()
    q = str(text).lower().replace("airport", "")
    q = " ".join(q.split(",")[0].split())  # 'Boston, MA' -> 'boston'
    if q.upper() in t.index:
        return q.upper()
    if len(q) < 3:
        return None  # too short to match safely; the agent asks the user to clarify
    pattern = r"\b" + re.escape(q) + r"\b"
    for column in ("city", "name", "keywords"):
        hits = t[t[column].str.contains(pattern, case=False, na=False, regex=True)]
        if len(hits):
            return hits["passengers"].idxmax()  # the largest airport that matches
    return None
