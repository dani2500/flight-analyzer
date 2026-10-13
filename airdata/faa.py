"""Live FAA airport status: the only data that is not read from the local store."""
import threading
import time
import xml.etree.ElementTree as ET

import config
from airdata import sources

_cache = {"expires": 0.0, "events": {}}  # events: airport code -> list of event dicts
_lock = threading.Lock()                 # one fetch at a time; the others reuse its result


def _fetch_events():
    """Download and parse the whole feed once.

    Returns:
        A dict from airport code to its list of event dicts.
    """
    root = ET.fromstring(sources.get(config.FAA_STATUS_URL).content)
    events = {}
    for delay_type in root.iter("Delay_type"):
        if "Closure" in (delay_type.findtext("Name") or ""):
            continue  # closure notices are mostly night/general-aviation NOTAMs, not congestion
        for item in delay_type.iter():
            code = item.findtext("ARPT")
            if code:
                detail = {c.tag: " ".join("".join(c.itertext()).split())
                          for c in item if c.tag != "ARPT"}
                events.setdefault(code, []).append({"type": delay_type.findtext("Name"), **detail})
    return events


def _events():
    """The parsed feed, refetched at most once per FAA_CACHE_TTL_S (a failure: FAA_ERROR_TTL_S)."""
    with _lock:
        if time.monotonic() >= _cache["expires"]:
            try:
                _cache["events"] = _fetch_events()
                ttl = config.FAA_CACHE_TTL_S
            except Exception as e:  # live feed is context only; never fail an answer over it
                _cache["events"] = {None: [{"type": "unavailable",
                                            "detail": f"FAA status feed error: {e}"}]}
                ttl = config.FAA_ERROR_TTL_S
            _cache["expires"] = time.monotonic() + ttl
        return _cache["events"]


def faa_status(code):
    """Live FAA (Federal Aviation Administration) delay programmes for one airport.
    Returns [] when there are none. The feed is cached for FAA_CACHE_TTL_S seconds.

    Args:
        code: The airport's FAA/IATA code, e.g. "SFO".

    Returns:
        A list of event dicts, [] when there are none, or one "unavailable" entry when the
        feed cannot be read.
    """
    events = _events()
    if None in events:  # the feed could not be read
        return list(events[None])
    return list(events.get(code, []))
