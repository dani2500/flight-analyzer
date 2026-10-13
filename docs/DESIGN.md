# Design: Airport Investment Agent

An analyst asks, in plain English, which US airports are good renovation candidates. The
agent ranks or compares airports with fixed scoring rules over public aviation data,
explains the result, and keeps context for follow-ups.

**Scope in one line.** "Profitable" is mapped to *capacity pressure*: full planes, growing
traffic, scale, and an airfield that can take more flights. There is no cost or revenue
data, so this is not a return-on-investment model.

## Where and how AI is used

The language model has two jobs: (1) pick one of three tools and fill in its arguments,
(2) turn the tool's JSON into a short paragraph. It never computes, ranks or recalls a
number. The page renders the table, breakdown, reasons and assumptions straight from the
tool output, so the figures on screen are correct even when the model's wording is not.
The "why" comes from rules in `scoring.drivers`, not from the model.

Follow-ups work because the conversation, including earlier tool results, is sent back
each turn (last 16 messages, trimmed at a user message). A turn is committed to the
history only when it completes, so a model failure leaves the conversation intact.

```
Browser (one page, jQuery, Web Speech API)  --POST /api/chat-->  app.py (Flask)
assistant/agent.py   tool-calling loop around a local Ollama model, history per session
assistant/tools.py   rank_airports / compare_airports / explain_metric
analysis/metrics.py  registry of askable metrics: label, caveats, explain breakdown
analysis/scoring.py  pure functions: metric columns, percentile ranks, reasons
airdata/             downloads and reads the datasets, regions, live FAA status
config.py            every threshold and weight
```

## Data

| Source | Access | Gives |
|---|---|---|
| BTS T-100 (Bureau of Transportation Statistics) | Socrata **API**, at server start | Monthly passengers, seats, departures (last 48 months) |
| FAA NAS status | **API**, live per question | Current delay programmes and their cause |
| BTS On-Time Performance | **File download** (one monthly zip, ~30 MB) | Delays, taxi-out, flights of 2,500+ miles |
| OurAirports | **File download** (CSV) | City, state, runway count |

No source needs a key or an account. Datasets are downloaded into `data/` at server start
(in the background; the chat is locked until they all exist) and are read-only afterwards.
Each file is written under a temporary name and renamed, so an interrupted download never
leaves a partial file. Refreshing is a deliberate step: `python -m airdata --force`.

## Scoring methodology

**Peer set.** US airports with at least 100,000 passengers in the last 12 months (228).
"Percentile rank" always means rank within this set, 0-100.

**Congestion index (0-100).** Mean of the percentile ranks of: share of departures delayed
15+ minutes, average taxi-out time, and departures per runway per day.

**Unmet demand (proxy, % of passengers).** For each of the last 12 months,
`max(0, passengers - 80% x seats)`, summed and divided by the year's passengers. When
flights run fuller than about 80%, some travellers can no longer get the flight they want,
so passengers carried above that level stand in for demand being turned away. It is a
share, not a count, because the count just ranks airports by size (ATL, DFW, ORD first).
The explanation is rule-based: load factor, passengers vs seats growth, airfield
congestion, seasonality.

**Long-haul share (%).** Scheduled domestic departures of 2,500+ miles over all scheduled
domestic departures in the month. The international share is reported next to it.

**Expansion opportunity score (0-100).** Weighted sum of percentile ranks:

| Component | Weight | Why |
|---|---|---|
| Load factor | 35% | Full planes mean demand is pressing on supply |
| Passenger growth (3-year annualised) | 30% | Demand is still rising |
| Passenger volume | 20% | A percent of added capacity is worth more at a bigger airport |
| Airfield headroom (100 - congestion) | 15% | A terminal only adds traffic if the runways can take more flights |

## Uncertainty

- **Weights are a judgement call, and the ranking is sensitive to them.** Every airport's
  rank is recomputed under three other weightings (equal; growth-heavy; volume-heavy) and
  the answer says whether it holds. Measured on the current data, the configured top 10
  keeps 9 places under equal weights, 7 under growth-heavy and only 2 under volume-heavy.
  An investor who cares about absolute size should read the volume-heavy ranking.
- **The score favours small, fast-growing airports** (Provo, Knoxville) over large hubs,
  because load factor and growth together weigh 65%.
- **Missing data is flagged, not hidden.** Five peer airports have no on-time data (their
  congestion uses runway use alone) and an airport without a 3-year history is scored as
  the median on growth; both are stated in the reasons.
- **One month of on-time data** (April 2026) drives all delay and taxi-out figures, so that
  month's weather matters. A year would smooth it but multiplies the download.

## Key tradeoffs

- **Local model instead of a hosted one.** Free, no credentials, data stays on the machine.
  The cost is speed (up to a minute per answer on a CPU) and a weaker model, which is why
  the model is kept away from the numbers and given only three tools.
- **Three tools instead of many.** Fewer choices make a small model more reliable. The
  price is that `compare_airports` returns every metric even when one was asked for.
- **Percentile ranks instead of absolute thresholds.** Robust and needs no calibration, but
  a score says "better than most peers", not "good in absolute terms".
- **Data downloaded at start, not per question.** Answers are fast and consistent and the
  app survives a source being down; the price is a first start of several minutes and data
  only as fresh as the last refresh.
- **Built for a handful of users.** One process; history is in memory and lost on restart;
  the local model answers one question at a time, so simultaneous users queue.

## Assumptions and limits

- Unmet demand is inferred from load factors; refused demand is not published anywhere.
- Delay, taxi-out and long-haul figures cover domestic flights by large US carriers.
- International flights are counted but not classified by distance.
- T-100 lags about five months.
- Runway count ignores layout, gates and slot rules.
- Airport names are matched as typed (codes, city, airport name); nicknames such as "LA"
  depend on the model turning them into codes.
- US states only; territories are excluded.

## With more time

See [TODO.md](TODO.md).

## Appendix: model choice

Default `qwen2.5:7b` (open weights, Apache 2.0). Tool selection is the whole job, Qwen 2.5
emits function calls in a format Ollama parses natively, and without a GPU the practical
ceiling is about 8B parameters. Other families (Llama 3.1 8B, Mistral Nemo, Gemma, Phi-4
mini, Granite 3.3) were judged from their documentation, not measured.

Measured with `evals/model_comparison.py` on a CPU-only desktop with 32 GB RAM (Ollama
0.40.3, October 2026), one run of ten questions each:

| Model | Passed | Total time | Notes |
|---|---|---|---|
| `qwen2.5:7b` | 9/10 | 211 s | Missed "Tell me about Denver airport" (answered without a tool) |
| `qwen3:8b`, thinking on | 9/10 | 749 s | Same score, about 3.5 times slower |
| `qwen3:8b`, thinking off | 8/10 | 243 s | Answered two `explain_metric` questions without a tool |
| `qwen2.5:14b` | 5/10 and 6/10 | 204 s and 296 s | Empty replies: tokens generated, neither text nor a tool call |

A one-question difference is not significant; the 14b failures and the cost of thinking
mode are. The context window is set to 8,192 tokens (`OLLAMA_NUM_CTX`) because Ollama's
default of 4,096 silently drops the oldest messages.
