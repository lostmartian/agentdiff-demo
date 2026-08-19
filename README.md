# agentdiff-demo

A live reference implementation showing **AgentDiff** gating a real agent in CI.
It is intentionally a small, realistic project: a real Gemini tool-calling
agent, a committed baseline trace, and a GitHub Action that gates every run and
**auto-posts a PR-ready report** onto the pull request.

This document explains the setup, how the pieces fit together, and every case
demonstrated across the repo's branches and pull requests.

---

## 1. Overview

The pipeline is:

1. A `pull_request` (or push / manual dispatch) triggers the workflow.
2. CI runs the **real** `gemini-3.6-flash` agent (`scripts/run_agent.py`), which
   writes a *candidate* trace in the generic format.
3. The **agentdiff-check** action compares the candidate against the committed
   baseline (`traces/gemini_baseline.json`) and computes the gate metrics.
4. If the run regresses, the job fails. On `pull_request` events the action also
   **auto-posts** the report as a comment on the PR that triggered the run.

Everything is real: the trace is produced by a live model call, the API key is a
GitHub secret, and the gates run against actual divergence, loop, and cost
values.

---

## 2. Files

| Path | Purpose |
| --- | --- |
| `scripts/run_agent.py` | Real Gemini tool loop; writes a generic-format trace JSON. |
| `traces/gemini_baseline.json` | Committed baseline from an earlier good run. |
| `.github/workflows/agent-gate.yml` | Generates the candidate live, then gates it. |

---

## 3. Setup

1. **Clone** this repo.
2. **Add the API key** as a GitHub Actions secret:
   **Settings → Secrets and variables → Actions → New repository secret** →
   `GEMINI_API_KEY` (a real Google AI Studio key).
3. **Push** (or open a PR). Watch `.github/workflows/agent-gate.yml` run.

### Required workflow permission

To post the PR comment, the built-in `GITHUB_TOKEN` needs write access to the
PR. Add this to the workflow (already included here):

```yaml
permissions:
  contents: read
  pull-requests: write
```

No manual token is needed — GitHub injects `GITHUB_TOKEN` automatically; the
`permissions` block just grants it the ability to comment.

---

## 4. How the action is referenced

```yaml
- uses: lostmartian/agentdiff/.github/actions/agentdiff-check@v0.2.2
  with:
    baseline: traces/gemini_baseline.json
    candidate: run.json
    max-divergence: "0.3"
    max-loops: "0"
    # Optional: auto-post the report onto the triggering PR.
    pr: ${{ github.event.pull_request.number || github.event.inputs.pr }}
    github-token: ${{ secrets.GITHUB_TOKEN }}
```

### Inputs

| Input | Default | Description |
| --- | --- | --- |
| `baseline` | *(required)* | Path to the stored baseline trace JSON. |
| `candidate` | *(required)* | Path to the candidate trace JSON. |
| `package` | `agent-trajectory-diff` | Python package spec (PyPI name, `git+https://…`, or a local path). |
| `adapter` | `auto` | Telemetry adapter: `auto`, `generic`, `openinference`, `langfuse`, `langsmith`, `openai_agents`. |
| `max-divergence` | `0.3` | Maximum Trajectory Divergence Index (TDI). |
| `max-loops` | `0` | Maximum loop count. |
| `max-cost-delta` | `10.0` | Maximum cost increase percentage. |
| `update-baseline` | `false` | Overwrite the stored baseline when the run is clean. |
| `pr` | *(empty)* | GitHub PR number to post the report comment to. |
| `github-token` | *(empty)* | Token used to post the comment (required when `pr` is set). |

The action installs the package, runs
`agentdiff <baseline> <candidate> --fail-on-regression`, and exits non-zero on a
regression. Pin the action to a release tag (e.g. `@v0.2.2`) for reproducibility.

---

## 5. What the PR comment looks like

When `pr` is set, the action posts a compact, reviewer-ready report. The
markdown is produced by the library's `generate_pr_markdown()` and includes:

- **Status** (`✅ PASSED` / `⛔ FAILED`) and the gate table (TDI, loops, cost).
- **Root cause** — the culprit step and why.
- **Collapsed divergence tree** — long matched runs are folded into
  `· · · N matched step(s) · · ·`; only divergent steps are shown (`+` added,
  `−` removed, `~` changed), capped to stay small.
- **Loops detected**, if any.

Example (a clean run):

```markdown
## AgentDiff — Trajectory Regression Check

**Status:** ✅ **PASSED**

| Gate | Value | Threshold |
| :--- | :--- | :--- |
| TDI | `0.0000` | ≤ `0.3` |
| Loops | `0` | ≤ `0` |
| Cost delta | `+12.77%` | ≤ `100.0%` |

### Divergence tree

baseline [3 steps] vs candidate [3 steps]
     1 · gemini_tool_decision
     2 · get_user_database_stats
     3 ~ gemini_synthesis   (changed)
```

The comment is posted **even when the gate blocks** — the failure report lands
on the PR that regressed, so reviewers see *why*.

---

## 6. Cases demonstrated across branches and PRs

The repo was built to show the full lifecycle. All PRs are left open as
reference examples.

| PR | Branch | Change | Gate outcome |
| --- | --- | --- | --- |
| #1 | `docs/clean-pr` | Docs only (no functional change) | ✅ passes |
| #2 | `fix/prompt-regression` | Agent prompt now forces a redundant call | ⛔ **blocked** (loop) + FAILED comment |
| #3 | `feat/pr-comment` | Adds automatic PR-comment posting | ✅ passes + auto-posted PASSED comment |

What each shows:

- **PR #1** — a harmless change passes the gate.
- **PR #2** — a real prompt change makes the live agent loop
  (`get_user_database_stats` twice). The gate blocks the job (`TDI 0.1429`,
  `Loops 1`) and auto-posts a ⛔ FAILED comment with the root cause and the loop
  tree.
- **PR #3** — the `pr` input resolves to `github.event.pull_request.number`, so
  opening/updating the PR auto-posts the report to that PR. This is the
  **real-life** flow: no manual PR number.

### Trying the cases yourself

```bash
# Open a clean PR (gate should pass)
git checkout -b my/clean main
git commit --allow-empty -m "chore: no change"
git push -u origin my/clean
gh pr create --base main --head my/clean --title "clean"
gh pr checks <N>

# Open a regressive PR (gate should block)
#   -> edit the pass-job prompt in .github/workflows/agent-gate.yml to the
#      redundant-call prompt, then push.

# Manual run that posts a FAILED loop comment to a PR
gh workflow run agent-gate.yml \
  --ref feat/pr-comment \
  -f pr=<N> \
  -f prompt="Query user stats for NY. Call get_user_database_stats twice to confirm the numbers are consistent."
```

---

## 7. FAQ

**Does the action create the PR?** No. It *posts a comment* to an existing PR
via `--pr`. Creating PRs is out of scope; the action reports on a run that is
already happening in CI.

**How do I reproduce locally?** Run the agent and diff without GitHub:

```bash
pip install google-genai agent-trajectory-diff
export GEMINI_API_KEY=...
python scripts/run_agent.py --prompt "Retrieve the database count of active users for state NY." --out run.json
agentdiff traces/gemini_baseline.json run.json --fail-on-regression --format pr
```

**Why is `continue-on-error` on the blocking job?** Only so the demo workflow
stays green while still showing the gate fire. In a real setup you remove it and
let the failed job block the merge.

**Why is `max-cost-delta` high on some jobs?** Live token counts vary run to
run, so a strict cost gate can flake on clean runs. This repo keeps the
interesting gates tight (divergence, loops) and relaxes cost for the demo.