import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app  # noqa: E402
from airdata import sources  # noqa: E402
from assistant import agent  # noqa: E402


@pytest.fixture
def client():
    return app.app.test_client()


def test_chat_is_locked_and_page_shows_preparation_until_data_is_ready(monkeypatch, client):
    monkeypatch.setattr(sources, "ready", lambda: False)
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 503
    prep_tag = re.search(rb'<div id="prep"[^>]*>', client.get("/").data).group(0)
    assert b"hidden" not in prep_tag


def test_status_reports_the_dataset_being_downloaded(monkeypatch):
    current = sources.DATASETS[-1]
    monkeypatch.setitem(sources._progress, "downloading", current.path)
    files = sources.status()["files"]
    assert [f["downloading"] for f in files] == [False] * (len(files) - 1) + [True]


@pytest.mark.parametrize("payload", [None, [], "text", {}, {"message": "  "}, {"message": 5}])
def test_chat_rejects_a_missing_or_malformed_message(monkeypatch, client, payload):
    monkeypatch.setattr(sources, "ready", lambda: True)
    assert client.post("/api/chat", json=payload).status_code == 400


def test_model_errors_are_shown_as_502(monkeypatch, client):
    monkeypatch.setattr(sources, "ready", lambda: True)

    def down(*_):
        raise agent.ModelError("Cannot reach Ollama at http://localhost:11434. Is it running?")

    monkeypatch.setattr(agent, "ask", down)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 502 and "Ollama" in r.get_json()["error"]


def test_unexpected_errors_do_not_leak_details(monkeypatch, client):
    monkeypatch.setattr(sources, "ready", lambda: True)

    def broken(*_):
        raise KeyError("secret_internal_column")

    monkeypatch.setattr(agent, "ask", broken)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 500 and "secret_internal_column" not in r.get_json()["error"]
