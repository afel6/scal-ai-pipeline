# Mock-provider scenarios — the offline regression corpus (D2)

Each JSON file here is a **scenario**: what the model says, turn by turn, when the
chat adapter runs in `mock` scripted mode (`llm_adapter.MockScript`). A scenario
never touches the network; the real tools run on a seeded session cache and the
real guards (tool-call ledger, citation gate, provenance tokens, plot/A3
provenance) run on the real answer-assembly path. One scenario = one defect this
project found in a production path, replayed offline forever.

## Shape

```json
{
  "name": "<file stem>",
  "description": "which defect this replays and what the guard must do",
  "on_exhausted": "error",            // or "null": fall back to null mode after the last step
  "steps": [
    {"assistant": {"text": "", "tool_calls": [{"name": "fit_petrophysical_curve", "args": {"model": "ri"}}]}},
    {"assistant": "plain text answer"},
    {"error": "HTTP 503 upstream"},   // raises ChatAdapterError, fires the failure hook
    {"timeout": {"after": 300}},      // sleeps via adapter.sleeper (inject it in tests), then fails
    {"slow": {"delay": 5, "text": "late but complete"}}
  ]
}
```

The chat loop calls the model once per turn: a turn with `tool_calls` is followed
by another call carrying the tool results; a text-only turn ends the conversation
(max 4 turns). Every call is recorded in `script.transcript` (OpenAI-shaped
messages + tool names) so a test can assert on exactly what the model was sent.

## Writing a scenario test

Use `tests/scenario_support.py`:

```python
run = run_scenario("my_scenario", sid="d2-my-scenario", question="…", n=1.85)
run.reply            # the assembled answer (tokens resolved, gate applied)
run.ledger           # tool-call ledger rows for the sid (status, values)
run.transcript       # what the model saw at each step
run.calls("fit_petrophysical_curve"); run.tool_messages(step)
```

`n` is the TRUE Archie exponent of the seeded Sw/RI sheet: `n < 1.5` makes the
cache-path fit **refuse**; `1.5 ≤ n ≤ 3.0` makes it **succeed** and record the
fitted value on the ledger.

Every scenario test file carries a **guard-off counterpart**: a test that
monkeypatches the guard away and asserts the defect *does* reach the caller.
That counterpart is the durable proof the scenario is load-bearing — a scenario
whose counterpart cannot fail is decorative. Run a new file twice: same input,
same output, every time.

## What a green corpus proves — and what it cannot

Green scenarios prove the **plumbing**: guards fire, provenance propagates,
pass-through holds. They prove nothing about **model behaviour** — which agent
the supervisor routes to, which tool the model chooses or whether it retries
around a refusal, whether it obeys a 1471-line prompt at length, contamination
and recitation rates, whether it restates a value the tool did not produce.
Those are model properties, measured only by the four-protocol acceptance gate
on a real model. Green mock tests **plus** the gate is the full picture.
