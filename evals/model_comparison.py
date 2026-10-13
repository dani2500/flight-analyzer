"""Checks that the model picks the right tool and arguments. Needs Ollama running.

A developer tool for comparing models and prompt changes; the app never imports it.
Run it from the project root:

    python -m evals.model_comparison
    OLLAMA_MODEL=<name> python -m evals.model_comparison

Each conversation is a list of turns: (question, expected tool, expected arguments).
The expected tool may be a tuple when more than one tool is a correct choice.
Expected arguments are compared case-insensitively as substrings, so 'LAX' matches
['LAX', 'SNA']. Tool None means the agent should answer without numbers (out of scope).
"""
import json
import time

import config
from assistant import agent

CONVERSATIONS = [
    [("Which airports in New England are strong candidates for terminal expansion?",
      "rank_airports", {"region": "new england", "metric": "expansion_score"}),
     ("And in the Midwest?", "rank_airports", {"region": "midwest", "metric": "expansion_score"})],
    [("Compare LA and Santa Ana airport congestion levels.",
      "compare_airports", {"airports": "la"}),
     ("And how does Boston compare?", "compare_airports", {"airports": "bos"})],
    [("What is the percentage of long haul flights out of Anchorage airport?",
      "explain_metric", {"airport": "anc", "metric": "pct_long_haul"})],
    [("What is the unmet flight demand in SFO airport and why?",
      "explain_metric", {"airport": "sfo", "metric": "unmet_demand"})],
    [("Top 3 most congested airports in Texas", "rank_airports",
      {"region": "tex", "metric": "congestion", "top_n": "3"})],
    [("Tell me about Denver airport", ("compare_airports", "explain_metric"), {})],
    [("How many dollars would a new terminal at JFK return?", None, {})],
    [("Is Heathrow a good investment?", None, {})],
]


def matches(expected_tool, expected_args, trace):
    if expected_tool is None:
        # Out of scope: no tool, or a tool that correctly reported an error.
        return all("error" in step["result"] for step in trace)
    allowed = (expected_tool,) if isinstance(expected_tool, str) else expected_tool
    if not trace or trace[0]["tool"] not in allowed:
        return False
    actual = trace[0]["arguments"]
    return all(want in json.dumps(actual.get(key, "")).lower()
               for key, want in expected_args.items())


def main():
    passed = total = 0
    started = time.time()
    for n, conversation in enumerate(CONVERSATIONS):
        for question, tool, args in conversation:
            t0 = time.time()
            out = agent.ask(f"eval-{n}", question)
            ok = matches(tool, args, out["trace"])
            passed, total = passed + ok, total + 1
            called = [(s["tool"], s["arguments"]) for s in out["trace"]]
            print(f"{'PASS' if ok else 'FAIL'} {time.time() - t0:5.1f}s  {question}\n"
                  f"      called: {called or 'no tool'}")
    print(f"\n{config.OLLAMA_MODEL}: {passed}/{total} passed in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
