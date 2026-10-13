"""Region and state names: turns what a user (or the model) typed into state postal codes."""
from functools import lru_cache

import pandas as pd

import config

# US Census Bureau divisions (the official grouping of states); regions are built from them.
# https://www2.census.gov/geo/pdfs/maps-data/maps/reference/us_regdiv.pdf
# The Census has two levels: nine finer divisions, and four coarse regions (Northeast,
# Midwest, South, West) that are each made of divisions. People ask at both levels
# ("New England" and "the Midwest"), so REGIONS below holds every name a user can ask for:
# the divisions are copied in, and the regions are built from them so each state list is
# written once.
DIVISIONS = {
    "new england": ["CT", "ME", "MA", "NH", "RI", "VT"],
    "middle atlantic": ["NJ", "NY", "PA"],
    "east north central": ["IL", "IN", "MI", "OH", "WI"],
    "west north central": ["IA", "KS", "MN", "MO", "NE", "ND", "SD"],
    "south atlantic": ["DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"],
    "east south central": ["AL", "KY", "MS", "TN"],
    "west south central": ["AR", "LA", "OK", "TX"],
    "mountain": ["AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"],
    "pacific": ["AK", "CA", "HI", "OR", "WA"],
}
REGIONS = {
    **DIVISIONS,
    "northeast": DIVISIONS["new england"] + DIVISIONS["middle atlantic"],
    "midwest": DIVISIONS["east north central"] + DIVISIONS["west north central"],
    "south": (DIVISIONS["south atlantic"] + DIVISIONS["east south central"]
              + DIVISIONS["west south central"]),
    "west": DIVISIONS["mountain"] + DIVISIONS["pacific"],
    "west coast": ["CA", "OR", "WA"],  # not a Census grouping, but what people ask for
}
REGION_ALIASES = {"mid atlantic": "middle atlantic"}
ALL_US = {"", "us", "usa", "all", "united states", "nationwide"}


@lru_cache(maxsize=1)
def states():
    """{'massachusetts': 'MA', ...} from the local file."""
    df = pd.read_csv(config.STATES_CSV, keep_default_na=False)
    return dict(zip(df["name"], df["code"]))


def resolve_region(text):
    """'New England', 'California', 'TX', 'US' -> list of state codes, or None for all.

    Args:
        text: A Census region or division, a state name or postal code, or an all-US word
            such as "US" or "nationwide". Empty or None means all of the US.

    Returns:
        A list of state postal codes, or None when the whole US is meant.

    Raises:
        ValueError: The text is not a known region or state; the message lists the choices.
    """
    q = " ".join(str(text or "").lower().replace("-", " ").split())
    q = REGION_ALIASES.get(q, q)
    if q in ALL_US:
        return None
    if q in REGIONS:
        return REGIONS[q]
    if q in states():
        return [states()[q]]
    if q.upper() in states().values():
        return [q.upper()]
    raise ValueError(f"Unknown region '{text}'. Use a US state or a Census region/division: "
                     + ", ".join(REGIONS))
