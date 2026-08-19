# agentdiff-demo

A tiny, real project showing **AgentDiff's** GitHub Action gating a live agent
run in CI. It's meant to look like the kind of small agent project you'd clone:
a real Gemini tool-calling agent, a committed baseline trace, and a workflow
that gates every run against that baseline.

## What it does

Every push runs a real `gemini-3.6-flash` agent (a DB-stats tool loop) that
writes a *candidate* trace. The **agentdiff-check** action then diffs it against
the committed baseline and fails the job on trajectory divergence, loops, or
cost spikes:

- **Clean run** -> candidate matches the baseline -> gate **passes**.
- **Bad prompt** (forces a redundant tool call) -> loop detected -> gate
  **blocks**.

The `block` job uses `continue-on-error: true` only so the demo workflow stays
green while still showing the gate firing; in a real setup you would let it
fail to block the merge.

## Setup (2 minutes)

1. Clone this repo.
2. Add a GitHub Actions secret: **Settings → Secrets and variables → Actions →
   New repository secret**:
   - `GEMINI_API_KEY` — a real Google AI Studio key.
3. Push. Watch `.github/workflows/agent-gate.yml` run.

## Files

| Path | Purpose |
| --- | --- |
| `scripts/run_agent.py` | Real Gemini tool loop; writes a generic trace JSON. |
| `traces/gemini_baseline.json` | Committed baseline from an earlier good run. |
| `.github/workflows/agent-gate.yml` | Generates the candidate live, then gates it. |

## How the action is referenced

```yaml
- uses: lostmartian/agentdiff/.github/actions/agentdiff-check@v0.2.1
  with:
    baseline: traces/gemini_baseline.json
    candidate: run.json
    max-divergence: "0.3"
    max-loops: "0"
```

`agent-trajectory-diff` is installed from PyPI (the action's default). Pin
`@v0.2.1` (or the tag you're adopting) for reproducible gates.