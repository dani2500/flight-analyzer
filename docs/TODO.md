# With more time

Not built, roughly in order of value. The reasoning behind the current design is in
[DESIGN.md](DESIGN.md).

1. **Answer speed.** Show the tool's table as soon as it exists and stream the model's
   sentence after it; add a hosted-model option behind the same tool interface.
2. **Check the model's wording against the data.** Verify that every number in the answer
   appears in the tool result, and retry once when the model answers without a tool.
3. **Better data.** Twelve months of on-time data; route-level T-100 so long-haul covers
   international flights; terminal capacity and project cost data to estimate return.
4. **Scheduled refresh** without a restart, picking the latest on-time month automatically.
5. **Nickname resolution** ("LA", "NYC") from airport coordinates instead of the model.
6. **Concurrency.** Request queue with position feedback; evict idle sessions (they are
   never removed today); shared session storage before running more than one worker.
7. **Larger eval set** with follow-up conversations, run on every change; repeat the model
   comparison on a GPU.
8. **Logging.** Replace the single `app.logger.exception` in `app.py` with structured logs
   per request: question, tool called and arguments, result size, model and tool latency,
   and errors, tagged with a session id so a bad answer can be traced and replayed.
9. **Engineering.** CI for the offline tests, tests for `airdata/` against recorded
   fixtures, a health endpoint, a Docker image with the data.
10. **Mobile.** Mobile layout needs to be handled.
