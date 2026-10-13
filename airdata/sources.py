"""The local dataset store: downloads the BTS and OurAirports files into data/ and reports
on them. Pure I/O; the arithmetic lives in analysis/scoring.py and reading the files in store.py.
"""
import io
import os
import time
import zipfile
from typing import Callable, NamedTuple

import pandas as pd
import requests
import truststore

import config

_trust_injected = False


def _use_system_certificates():
    """Verify HTTPS against the operating system's certificate store, so downloads also
    work behind corporate proxies / antivirus that re-sign traffic. Done on the first
    request rather than at import, so importing this module has no global side effect."""
    global _trust_injected
    if not _trust_injected:
        truststore.inject_into_ssl()
        _trust_injected = True


def get(url, timeout=config.HTTP_TIMEOUT_S, **params):
    _use_system_certificates()
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def fetch_t100_monthly():
    """Monthly passengers/seats/departures per origin airport for the last 4 years."""
    latest = get(config.T100_URL, **{"$select": "max(reporting_month) as m"}).json()[0]["m"]
    start = pd.Timestamp(latest) - pd.DateOffset(
        months=config.WINDOW_MONTHS * (config.GROWTH_YEARS + 1) - 1)
    rows = get(config.T100_URL, **{
        "$select": "origin_airport_code as code, reporting_month as month, "
                   "total_passengers as passengers, total_seats as seats, "
                   "total_departures as departures, "
                   "outbound_international as intl_departures",
        "$where": f"reporting_month >= '{start:%Y-%m-%d}T00:00:00' AND total_passengers > 0",
        "$limit": config.T100_ROW_LIMIT,
    }).json()
    df = pd.DataFrame(rows)
    df["month"] = pd.to_datetime(df["month"])
    for col in ["passengers", "seats", "departures", "intl_departures"]:
        df[col] = pd.to_numeric(df.get(col), errors="coerce").fillna(0)
    return df


def fetch_airports():
    """US airports: name, city, state, search keywords, open runway count."""
    airports = pd.read_csv(io.StringIO(get(config.AIRPORTS_URL).text))
    runways = pd.read_csv(io.StringIO(get(config.RUNWAYS_URL).text))
    airports = airports[(airports["iso_country"] == "US")
                        & airports["type"].str.endswith("airport")]
    count = runways[runways["closed"] == 0].groupby("airport_ident").size()

    def keyed(codes):
        return pd.DataFrame({
            "code": codes.values,
            "name": airports["name"].values,
            "city": airports["municipality"].values,
            "state": airports["iso_region"].str[3:].values,
            "keywords": airports["keywords"].fillna("").values,
            "runways": airports["ident"].map(count).fillna(1).astype(int).values,
        }).dropna(subset="code")

    # BTS keys on the FAA code. That is normally the IATA code, but when they differ
    # (e.g. PBI, renamed DJT) the ICAO ident minus its leading 'K' still matches.
    icao = airports["ident"].where(airports["ident"].str.fullmatch("K[A-Z]{3}")).str[1:]
    return (pd.concat([keyed(airports["iata_code"]), keyed(icao)])
            .drop_duplicates("code").set_index("code"))


def fetch_states():
    """US state names and postal codes, from OurAirports' regions file."""
    regions = pd.read_csv(io.StringIO(get(config.STATES_URL).text), keep_default_na=False)
    regions = regions[regions["iso_country"] == "US"]
    return pd.DataFrame({"name": regions["name"].str.lower().values,
                         "code": regions["local_code"].values})


def fetch_ontime():
    """One month of BTS (Bureau of Transportation Statistics) On-Time Performance (~600k flights, 30 MB zip) reduced to one
    row per origin airport. This is the slow download."""
    url = config.ONTIME_URL.format(year=config.ONTIME_YEAR, month=config.ONTIME_MONTH)
    raw = get(url, timeout=config.ONTIME_TIMEOUT_S).content
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = next(n for n in z.namelist() if n.endswith(".csv"))
        flights = pd.read_csv(z.open(name),
                              usecols=["Origin", "Distance", "DepDel15", "TaxiOut", "Cancelled"])
    flights["long_haul"] = flights["Distance"] >= config.LONG_HAUL_MILES
    flown = flights[flights["Cancelled"] == 0]
    out = pd.DataFrame({
        "scheduled_flights": flights.groupby("Origin").size(),
        "long_haul_flights": flights.groupby("Origin")["long_haul"].sum(),
        "pct_delayed_15": flown.groupby("Origin")["DepDel15"].mean() * 100,
        "avg_taxi_out_min": flown.groupby("Origin")["TaxiOut"].mean(),
    }).round(2)
    out.index.name = "code"
    return out


class Dataset(NamedTuple):
    """One file of the local store."""
    path: str
    description: str
    fetch: Callable[[], pd.DataFrame]  # how to download it
    keep_index: bool                   # whether the frame's index is data


DATASETS = [
    Dataset(config.T100_CSV, "BTS T-100 monthly traffic by airport", fetch_t100_monthly, False),
    Dataset(config.AIRPORTS_CSV, "OurAirports: city, state, runways", fetch_airports, True),
    Dataset(config.STATES_CSV, "OurAirports: US state names and codes", fetch_states, False),
    Dataset(config.ONTIME_CSV, f"BTS on-time summary, {config.ONTIME_PERIOD}", fetch_ontime, True),
]


# What download() is doing right now; the page polls this through status().
_progress = {"downloading": None, "error": None}


def ready():
    """True when every dataset is stored locally."""
    return all(os.path.exists(dataset.path) for dataset in DATASETS)


def status():
    """Which datasets are stored locally, with row counts and download dates."""
    files = []
    for dataset in DATASETS:
        stored = os.path.exists(dataset.path)
        entry = {"file": os.path.basename(dataset.path), "description": dataset.description,
                 "ready": stored, "downloading": _progress["downloading"] == dataset.path}
        if stored:
            with open(dataset.path, encoding="utf-8") as f:
                entry["rows"] = sum(1 for _ in f) - 1
            entry["downloaded"] = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(dataset.path)))
        files.append(entry)
    return {"ready": all(f["ready"] for f in files), "error": _progress["error"],
            "files": files}


def download(force=False):
    """Download whatever is missing (or everything, with force) into data/.

    The server runs this in a background thread and keeps the chat locked until every
    file exists, so nothing reads these files while they are written. Readers that cache
    the files (store.table, regions.states) must be cleared afterwards: use store.prepare.

    Args:
        force: Re-download every dataset, even if its file already exists.

    Returns:
        The same dict as status(), after the downloads.

    Raises:
        Exception: Whatever a download raised; the cause is also kept in status()["error"].
    """
    os.makedirs(config.DATA_DIR, exist_ok=True)
    _progress["error"] = None
    try:
        for dataset in DATASETS:
            if force or not os.path.exists(dataset.path):
                print(f"Downloading {dataset.description} ...", flush=True)
                _progress["downloading"] = dataset.path
                tmp = dataset.path + ".tmp"
                dataset.fetch().to_csv(tmp, index=dataset.keep_index)
                os.replace(tmp, dataset.path)  # an interrupted download leaves no half file
    except Exception as e:
        _progress["error"] = f"{dataset.description}: {e}"
        raise
    finally:
        _progress["downloading"] = None
    return status()
