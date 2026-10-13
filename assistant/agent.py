"""The agent: a small tool-calling loop around a local Ollama model.

The model does two things only: choose a tool with arguments, and turn the tool's JSON
into prose. It never computes a number.
"""
import inspect
import json
import threading

import requests

import config
from analysis import metrics
from assistant import tools

MAX_ROUNDS = 3
HISTORY_LIMIT = 16  # messages kept per session, enough for several follow-ups
MAX_SESSIONS = 200  # sessions kept; the least recently answered is dropped beyond this
NO_ANSWER = "I could not answer that. Please rephrase the question."
NO_ANSWER_WITH_DATA = "I could not put this into words; the figures are in the panels below."

SYSTEM_PROMPT = f"""You are an analyst assistant for a firm that invests in US airport \
modernization. You help find airports where renovation would pay off through more flight \
and passenger capacity.

Rules:
- Get every number from a tool. Never state a figure that is not in a tool result.
- Scope: US commercial airports only. If asked about anything else (non-US airports, \
costs, ROI in dollars, forecasts), say it is out of scope and what you can offer instead.
- For a follow-up question, reuse airports, regions and metrics from earlier turns.
- Answer in 2 to 4 plain-text sentences, no markdown and no lists: the conclusion first, \
then the reasons. The user already sees the full table, so do not repeat it.
- Give only reasons that appear in the tool's "reasons" or "breakdown". Do not add your own.
- When comparing airports, take which one is higher from "head_to_head", never by guessing.
- End with one line starting "Caveat:" naming the most relevant assumption.
- If a tool returns "error", tell the user plainly and ask for what is missing.

Metrics: {json.dumps(metrics.LABELS)}
Congestion is explained by delays, taxi-out time and departures per runway, not by load factor.
"Strong candidates for expansion" means metric expansion_score.
"Unmet demand" means metric unmet_demand. "Long haul" means metric pct_long_haul."""

TOOL_SCHEMAS = [tool.schema() for tool in tools.TOOLS]

_sessions = {}
_locks = {}                # one lock per session: two requests must not interleave a history
_guard = threading.Lock()  # protects _sessions and _locks themselves


class ModelError(RuntimeError):
    """The language model could not be reached or did not answer; the message is safe to show."""


def _chat(messages, with_tools=True):
    body = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0, "num_ctx": config.OLLAMA_NUM_CTX}}
    if with_tools:
        body["tools"] = TOOL_SCHEMAS
    try:
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", timeout=config.OLLAMA_TIMEOUT_S,
                          json=body)
    except requests.ConnectionError:
        raise ModelError(f"Cannot reach Ollama at {config.OLLAMA_URL}. Is it running?")
    except requests.Timeout:
        raise ModelError(f"The model did not answer within {config.OLLAMA_TIMEOUT_S} s.")
    if r.status_code != 200:
        raise ModelError(f"Ollama error {r.status_code}: {r.text[:300]}")
    return r.json()["message"]


def _run_tool(call):
    function = call.get("function") or {}
    name = function.get("name") or ""
    args = function.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return name, {}, tools.error("Tool arguments were not valid JSON.")
    tool = tools.REGISTRY.get(name)
    if tool is None:
        return name, args, tools.error(f"No such tool '{name}'.")
    try:  # check the names up front, so a bug inside a tool is not reported as bad arguments
        inspect.signature(tool.run).bind(**args)
    except TypeError as e:
        return name, args, tools.error(f"Bad arguments: {e}")
    try:
        return name, args, tool.run(**args)
    except (RuntimeError, ValueError) as e:  # e.g. data not downloaded yet
        return name, args, tools.error(str(e))
    except Exception as e:  # a tool bug or an argument of the wrong type: tell the model, keep the turn
        return name, args, tools.error(f"The tool failed on these arguments ({type(e).__name__}).")


def _trim(history):
    """The last HISTORY_LIMIT messages, starting at a user message.

    Cutting anywhere else could leave a tool result without the assistant call that
    produced it, which confuses the model.
    """
    kept = history[-HISTORY_LIMIT:]
    first_user = next((i for i, m in enumerate(kept) if m["role"] == "user"), None)
    return kept[first_user:] if first_user is not None else kept


def _session_lock(session_id):
    with _guard:
        if session_id not in _locks and len(_locks) >= 2 * MAX_SESSIONS:
            # Locks of sessions with no stored history (failed or reset) are never reused.
            for sid in [s for s, lock in _locks.items()
                        if s not in _sessions and not lock.locked()]:
                del _locks[sid]
        return _locks.setdefault(session_id, threading.Lock())


def _remember(session_id, history):
    """Store a session's history as the most recent one, dropping the oldest beyond MAX_SESSIONS."""
    with _guard:
        _sessions.pop(session_id, None)  # re-insert at the end: dicts keep insertion order
        _sessions[session_id] = history
        while len(_sessions) > MAX_SESSIONS:
            oldest = next(iter(_sessions))
            del _sessions[oldest]
            lock = _locks.get(oldest)
            if lock is not None and not lock.locked():
                del _locks[oldest]


def ask(session_id, question):
    """Answer one user message. Returns the prose answer and every tool call made.

    The turn is built on the side and added to the session history only when it
    completes, so a model failure leaves the conversation as it was.

    Raises:
        ModelError: The model could not be reached or did not answer.
    """
    with _session_lock(session_id):
        history = _sessions.get(session_id, [])
        turn = [{"role": "user", "content": question}]
        trace = []

        def context():
            return [{"role": "system", "content": SYSTEM_PROMPT}] + history + turn

        for _ in range(MAX_ROUNDS):
            reply = _chat(context())
            turn.append(reply)
            if not reply.get("tool_calls"):
                break
            for call in reply["tool_calls"]:
                name, args, result = _run_tool(call)
                trace.append({"tool": name, "arguments": args, "result": result})
                turn.append({"role": "tool", "tool_name": name, "content": json.dumps(result)})
        else:  # still calling tools after the last round: ask for the words, without tools
            reply = _chat(context(), with_tools=False)
            turn.append(reply)

        _remember(session_id, _trim(history + turn))
    answer = (reply.get("content") or "").strip()
    if not answer:
        answer = NO_ANSWER_WITH_DATA if trace else NO_ANSWER
    return {"answer": answer, "trace": trace}


def reset(session_id):
    """Forget a session. Waits for an answer in progress, so it cannot write the old history back."""
    with _session_lock(session_id):
        with _guard:
            _sessions.pop(session_id, None)
