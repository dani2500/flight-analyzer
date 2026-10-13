import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from assistant import agent, tools  # noqa: E402

CALL = {"role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": "rank_airports", "arguments": {}}}]}


def say(text):
    return {"role": "assistant", "content": text}


@pytest.fixture(autouse=True)
def clean_sessions(monkeypatch):
    monkeypatch.setattr(agent, "_sessions", {})
    monkeypatch.setattr(agent, "_locks", {})
    # The tool itself is not under test here (it needs the downloaded data).
    monkeypatch.setattr(agent, "_run_tool", lambda call: ("rank_airports", {}, {"title": "t"}))


def script(monkeypatch, replies):
    """Make the model return `replies` in order; an Exception in the list is raised."""
    queue, seen = list(replies), []

    def fake_chat(messages, with_tools=True):
        seen.append({"messages": messages, "with_tools": with_tools})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(agent, "_chat", fake_chat)
    return seen


def test_failed_turn_leaves_the_conversation_unchanged(monkeypatch):
    script(monkeypatch, [say("first answer")])
    agent.ask("s", "first question")
    before = list(agent._sessions["s"])

    script(monkeypatch, [CALL, agent.ModelError("Ollama is down")])
    with pytest.raises(agent.ModelError):
        agent.ask("s", "second question")
    assert agent._sessions["s"] == before


def test_trimmed_history_always_starts_at_a_user_message(monkeypatch):
    for n in range(10):
        script(monkeypatch, [CALL, say(f"answer {n}")])  # 4 messages per turn
        agent.ask("s", f"question {n}")
    history = agent._sessions["s"]
    assert 0 < len(history) <= agent.HISTORY_LIMIT
    assert history[0]["role"] == "user"


def test_rounds_exhausted_asks_for_words_without_tools(monkeypatch):
    seen = script(monkeypatch, [CALL] * agent.MAX_ROUNDS + [say("Here is the summary.")])
    out = agent.ask("s", "question")
    assert out["answer"] == "Here is the summary."
    assert [call["with_tools"] for call in seen] == [True] * agent.MAX_ROUNDS + [False]
    assert len(out["trace"]) == agent.MAX_ROUNDS


def test_empty_model_reply_gets_a_fallback_not_a_blank(monkeypatch):
    script(monkeypatch, [say("")])
    assert agent.ask("a", "question")["answer"] == agent.NO_ANSWER
    script(monkeypatch, [CALL, say("")])
    assert agent.ask("b", "question")["answer"] == agent.NO_ANSWER_WITH_DATA


def test_sessions_do_not_share_history(monkeypatch):
    script(monkeypatch, [say("one"), say("two")])
    agent.ask("a", "question a")
    agent.ask("b", "question b")
    assert [m["content"] for m in agent._sessions["a"]] == ["question a", "one"]
    assert [m["content"] for m in agent._sessions["b"]] == ["question b", "two"]


def test_wrong_argument_names_are_reported_not_raised(monkeypatch):
    monkeypatch.undo()  # use the real _run_tool
    call = {"function": {"name": "rank_airports", "arguments": {"bogus": 1}}}
    name, _, result = agent._run_tool(call)
    assert name == "rank_airports" and "Bad arguments" in result["error"]


@pytest.mark.parametrize("raw, expected", [
    (-3, 1), (0, 1), (3, 3), ("7", 7), (999, 25), ("many", 5), (None, 5)])
def test_top_n_is_clamped(raw, expected):
    assert tools._clamp_top_n(raw) == expected
