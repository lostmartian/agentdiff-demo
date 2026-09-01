# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "agent-trajectory-diff @ git+https://github.com/kerrshift/agentdiff.git",
#     "google-genai",
# ]
# ///
"""Builds a statistical baseline envelope from N live agent runs.

Pillar 1 of AgentDiff 0.5.0: instead of one golden trace, record N runs of
the real agent and let the gate judge candidates against *normal variance*
(mean ± k·sigma bands). Run this once to bootstrap:

    GEMINI_API_KEY=... python scripts/make_envelope.py --runs 3
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from run_agent import run_agent  # noqa: E402

from agentdiff.loader import load_trace  # noqa: E402
from agentdiff.models.envelope import BaselineEnvelope  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        default="Retrieve the database count of active users for state NY.",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--out", default="baselines/default.envelope.json")
    parser.add_argument("--scenario", default="default")
    args = parser.parse_args()

    if not __import__("os").environ.get("GEMINI_API_KEY"):
        print("[Error] GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    tmp = Path(tempfile.mkdtemp(prefix="agentdiff-runs-"))
    traces = []
    for i in range(args.runs):
        data = run_agent(args.prompt, f"baseline-run-{i + 1}")
        path = tmp / f"run-{i + 1}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        traces.append(load_trace(str(path), "generic"))
        print(f"run {i + 1}/{args.runs}: {len(data['steps'])} steps, "
              f"{data['total_tokens']['total_tokens']} tokens")

    envelope = BaselineEnvelope.from_runs(traces, scenario=args.scenario)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(envelope.model_dump_json(), encoding="utf-8")
    print(f"envelope ({args.runs} runs, scenario={args.scenario}) -> {out}")


if __name__ == "__main__":
    main()
