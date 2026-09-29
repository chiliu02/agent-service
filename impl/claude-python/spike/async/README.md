# `spike/async/` — stdlib probes behind `learning-async-python.md`

These sit in `spike/` for the reason the rest of `spike/` does — probe scripts are
committed on purpose, as evidence — but they differ from their neighbours in two
ways worth stating so the convention is not silently bent:

- **They probe CPython, not the SDK.** Everything else in `spike/` measures
  `claude-agent-sdk` behaviour. These measure `asyncio`, `contextvars`,
  `anyio` and the subprocess/stream machinery underneath the service.
- **They are written up elsewhere.** SDK probes become numbered cases (`S1`–`S6`,
  `L1`–`L7`, `M1`) in `../../docs/claude-python-references.md`. These are written up in
  `learning-async-python.md`, which cites each script by name beside the
  transcript it produced. **Named rather than pathed**: that primer sits in the
  platform's `docs/conversations/`, which is untracked, so it is on its author's
  disk and in no clone — a path to it would resolve for one reader and dead-end
  for every other.

## Running them

```bash
uv run python -u spike/async/<name>.py
```

Every one is free — no API calls, no cost. `proc_probe.py` spawns short-lived
Python subprocesses and writes a marker file next to itself, which it removes.
All 27 pass on CPython 3.13.5 / Windows as of 2026-07-31.

## Why the transcripts in the doc are not enough on their own

Several results are **platform- or version-dependent**, and the doc says so where
it matters:

- Windows timer granularity (~15.6 ms) changes what `_ACLOSE_RETRY_INTERVAL_S`
  actually delivers — `loop_probe.py`
- `terminate()` and `kill()` are the same call on Windows — `proc_probe.py`
- the loop class differs by platform (`ProactorEventLoop` here, no `add_reader`)
  — `loop_probe.py`
- `anyio_probe.py` exercises the **asyncio backend only**; trio is not a
  dependency of this project, so every trio-specific claim in Part 14 is marked
  unverified

Re-run them rather than trusting a transcript recorded on someone else's machine.

## One that is deliberately unreproducible

`task_probe.py`'s F9 does **not** reproduce a task being garbage-collected
mid-flight. The weak registry is real — `asyncio/tasks.py` has
`_scheduled_tasks = weakref.WeakSet()` — but a runnable task stays reachable
through the loop's ready queue, so the failure is timing-dependent and did not
occur in 200 attempts. It is kept as a negative result, not deleted: the doc
states plainly that not reproducing it is not evidence it cannot happen.
