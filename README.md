# Airport Investment Agent

A chat agent that ranks and compares US airports as renovation candidates. It uses public
BTS and FAA data, fixed scoring rules, and a local LLM (Ollama) for the conversation.
No API keys, no accounts, no cost.

See [DESIGN.md](docs/DESIGN.md) for the scoring methodology, tradeoffs and where AI is used,
and [TODO.md](docs/TODO.md) for ideas not built yet.

## Example questions

- Which airports in New England are strong candidates for terminal expansion?
- Compare LA and Santa Ana airport congestion levels.
- What is the percentage of long haul flights out of Anchorage airport?
- What is the unmet flight demand in SFO airport and why?

Follow-ups such as "why is the first one ranked so high?" or "and how does Boston compare?"
keep the context of the conversation.

## Setup

Requires Python 3.12 and [Ollama](https://ollama.com).

```bash
ollama pull qwen2.5:7b
```

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

On macOS/Linux use `.venv/bin/python` instead of `.venv\Scripts\python`.

## Run

```bash
.venv\Scripts\python app.py
```

Open http://localhost:5000.

**The first start takes several minutes.** The server downloads its datasets into `data/`
(git-ignored) in the background; the BTS flight file is 30 MB from a slow server. Until
they are all there, the page shows a "Preparing data…" message with per-file progress and
the chat is locked and unlocks by itself. Progress is also printed in the terminal. Later
starts reuse the local files and take seconds. The "Data ready" indicator at the top right
of the page lists what is loaded.

Voice: in Chrome or Edge a microphone button appears next to the input, and "Read answers
aloud" speaks the reply.

## Configuration

| Environment variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `qwen2.5:7b` | Any Ollama model that supports tools |
| `OLLAMA_URL` | `http://localhost:11434` | Where Ollama listens |

`qwen2.5:7b` is the default because it scored best for its speed on a CPU-only machine.
`qwen3:8b` and `qwen2.5:14b` were also tried; results and reasons are in
[DESIGN.md](docs/DESIGN.md#model-choice).

Scoring thresholds and weights are in [config.py](config.py).

## Tests and eval

```bash
.venv\Scripts\python -m pytest
```

Unit tests for the scoring rules, the agent loop (with a stubbed model) and the web
endpoints; no network, data or LLM needed.

```bash
.venv\Scripts\python -m evals.model_comparison
```

A developer tool, not part of the app (see [evals/README.md](evals/README.md)). Runs a fixed
set of questions through the agent and checks it picks the right tool and arguments, to
compare models. Needs Ollama running and the data downloaded.

## Using the tools without the LLM

```bash
.venv\Scripts\python -c "from assistant import tools; import json; print(json.dumps(tools.rank_airports('New England'), indent=1))"
```

## Refreshing the data

Stop the server, then re-download everything and start it again:

```bash
.venv\Scripts\python -m airdata --force
```

To use a different on-time month, change `ONTIME_YEAR` / `ONTIME_MONTH` in `config.py`
first. Without `--force` the command downloads only what is missing, which is also a way
to fetch the data ahead of the first start.

The code layout is in [DESIGN.md](docs/DESIGN.md#where-and-how-ai-is-used).
