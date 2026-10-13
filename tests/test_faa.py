import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from airdata import faa, sources  # noqa: E402

FEED = b"""<AIRPORT_STATUS_INFORMATION>
  <Delay_type><Name>Ground Delay Programs</Name>
    <Ground_Delay_List><Ground_Delay><ARPT>SFO</ARPT><Reason>low ceilings</Reason>
      <Avg>45 minutes</Avg></Ground_Delay></Ground_Delay_List></Delay_type>
  <Delay_type><Name>Airport Closures</Name>
    <Airport_Closure_List><Airport><ARPT>BOS</ARPT><Reason>runway</Reason></Airport>
    </Airport_Closure_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


class Response:
    content = FEED


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setitem(faa._cache, "expires", 0.0)
    monkeypatch.setitem(faa._cache, "events", {})


def count_fetches(monkeypatch, behaviour):
    calls = []

    def get(url):
        calls.append(url)
        return behaviour()

    monkeypatch.setattr(sources, "get", get)
    return calls


def test_one_fetch_serves_several_airports(monkeypatch):
    calls = count_fetches(monkeypatch, Response)
    sfo, bos, jfk = faa.faa_status("SFO"), faa.faa_status("BOS"), faa.faa_status("JFK")
    assert len(calls) == 1
    assert sfo[0]["type"] == "Ground Delay Programs" and sfo[0]["Reason"] == "low ceilings"
    assert bos == [] and jfk == []  # closures are not congestion


def test_the_feed_is_refetched_after_the_ttl(monkeypatch):
    calls = count_fetches(monkeypatch, Response)
    faa.faa_status("SFO")
    monkeypatch.setitem(faa._cache, "expires", 0.0)
    faa.faa_status("SFO")
    assert len(calls) == 2


def test_a_failing_feed_is_reported_and_not_retried_per_airport(monkeypatch):
    def down():
        raise OSError("timeout")

    calls = count_fetches(monkeypatch, down)
    first, second = faa.faa_status("SFO"), faa.faa_status("BOS")
    assert len(calls) == 1
    assert first[0]["type"] == "unavailable" and "timeout" in first[0]["detail"]
    assert second == first
