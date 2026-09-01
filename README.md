# agentdiff-demo

A live reference implementation showing **AgentDiff** gating a real agent in
CI with the **0.5.0 statistical gate**. It is intentionally small and real: a
Gemini tool-calling agent, a committed **N-run baseline envelope**, a CI gate
that judges every run against *normal variance*, and a PR bot that
re-baselines on `/agentdiff approve` as **agentdiff-ci[bot]**.

---

## 1. What this demo shows

1. **Statistical baselines (Pillar 1)** — the golden baseline is not one trace
   but an envelope over 3 live runs (`baselines/default.envelope.json`). A
   candidate passes when *some* recorded run explains it and its resource
   profile sits within mean ± k·sigma bands. Flaky token counts no longer
   flip the gate.
2. **Honest gate (Pillars 2/3)** — cyclical tool loops and repeat-cap
   breaches are **hard blocks** (never blessable); path drift and cost spikes
   render as soft warnings a human may approve.
3. **The approve bot** — comment `/agentdiff approve` on a flagged PR and the
   bot re-records the golden baseline, commits it to the PR branch, and posts
   a green `AgentDiff Check` — as `agentdiff-ci[bot]` via the hosted identity
   service (`token.agentdiff.app`). Zero secrets, zero variables.
4. **Config-as-code** — all thresholds live in `agentdiff.toml`
   (`[scenario.default]`, tolerances, invariants), exactly what
   `agentdiff init` generates.

The pipeline: a PR records a fresh candidate trace from the **real** Gemini
agent → `agentdiff diff` gates it against the envelope → the PR comment shows
the verdict (human-first summary, gate details collapsed).

## 2. Files

| Path | Purpose |
| --- | --- |
| `scripts/run_agent.py` | Real Gemini tool loop; writes a full generic-format trace. |
| `scripts/make_envelope.py` | Records N live runs into a statistical baseline envelope. |
| `baselines/default.envelope.json` | The committed N-run baseline (created by the Record Baseline workflow). |
| `agentdiff.toml` | Gate configuration (statistical scenario, invariants, tolerances). |
| `.github/workflows/agentdiff.yml` | `AgentDiff Check` — records the candidate, gates, posts the PR report. |
| `.github/workflows/record-baseline.yml` | `Record Baseline` — one-click envelope bootstrap/re-record. |
| `.github/workflows/agentdiff-approve.yml` | The `/agentdiff approve` bot. |
| `traces/gemini_baseline.json` | Historical v1 single-trace baseline (kept for reference). |

## 3. Setup

1. Add the API key: **Settings → Secrets and actions → Actions → New
   repository secret** → `GEMINI_API_KEY`.
2. (Optional, branding only) Install the
   [AgentDiff CI App](https://github.com/apps/agentdiff-ci) on this repo —
   the hosted token service then mints `agentdiff-ci[bot]` identities
   automatically. Without it everything still works as
   `github-actions[bot]`.

> **Version note:** workflows currently install AgentDiff from `main`
> (`git+https://github.com/kerrshift/agentdiff.git`) because the statistical
> gate and approve bot ship with 0.5.0. After the `v0.5.0` tag, switch the
> three workflows to `pip install agent-trajectory-diff`.

## 4. Run it

```bash
# 1. Bootstrap the baseline (Actions → Record Baseline → Run workflow)
gh workflow run record-baseline.yml        # records 3 live runs, commits the envelope

# 2. Open any PR — AgentDiff Check gates it and posts the report
git checkout -b my/change main
git commit --allow-empty -m "chore: harmless change"
git push -u origin my/change
gh pr create --fill
gh pr checks                                # AgentDiff Check → PASSED + PR comment

# 3. Demo a BLOCKED gate (dispatch the loop prompt at any PR)
gh workflow run agentdiff.yml --ref my/change \
  -f prompt="Query user stats for NY. Call get_user_database_stats twice to confirm the numbers are consistent." \
  -f pr=<PR number>

# 4. Bless the new behavior from the PR thread
gh pr comment <N> --body "/agentdiff approve"
# → bot re-baselines, commits, posts a green AgentDiff Check as agentdiff-ci[bot]
```

## 5. Local reproduction

```bash
pip install "agent-trajectory-diff @ git+https://github.com/kerrshift/agentdiff.git" google-genai
export GEMINI_API_KEY=...

python scripts/make_envelope.py --runs 3          # record the envelope
python scripts/run_agent.py --prompt "Retrieve the database count of active users for state NY." --out traces/candidate.json
agentdiff diff baselines/default.envelope.json traces/candidate.json --scenario default --fail-on-regression
```

## 6. History

The v1-era demo (single static baseline, `agentdiff-check` action pinned to
0.2.x) lives in the history of PRs #1–#3 and `traces/gemini_baseline.json`.
This branch is the 0.5.0 story: statistical envelopes, honest gates, and the
approve bot.
