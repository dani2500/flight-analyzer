# evals

Developer tools for measuring the language model. **Not part of the app**: the server never
imports anything from this folder, and it is not run by `pytest`.

| File | Purpose |
|---|---|
| `model_comparison.py` | Asks the real model a fixed set of questions and checks that it picks the right tool and arguments. Use it to compare models or to see whether a prompt or tool-description change helped. |

## Run

From the project root, with Ollama running and the data downloaded:

```bash
.venv\Scripts\python -m evals.model_comparison
```

To try another model, set `OLLAMA_MODEL` first (for example `qwen2.5:14b`). The output is
one PASS/FAIL line per question and a total such as `qwen2.5:7b: 7/8 passed in 90s`.

## Why it is not a unit test

It needs Ollama, takes up to a minute per question, and a model's choices can vary between
runs, so it cannot be a reliable pass/fail check. The deterministic code is covered by
`tests/`.
