# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "agent-trajectory-diff",
#     "google-genai",
# ]
# ///
"""A small real agent: answers DB-stat questions with the Gemini tool loop.

Writes a generic-format trace JSON (the *candidate* for a given run). CI calls
this with a prompt, then AgentDiff compares the resulting trace against the
stored baseline to gate regressions.

Usage:
    GEMINI_API_KEY=... python scripts/run_agent.py --prompt "..." --out run.json
"""

import argparse
import json
import os
import sys

from google import genai
from google.genai import types

COST_PER_TOKEN = 0.000000075


def get_user_database_stats(state: str) -> str:
    """Real tool: count of active users + revenue for a US state."""
    db = {
        "NY": {"users": 1250, "revenue": 45000},
        "CA": {"users": 3400, "revenue": 128000},
        "TX": {"users": 2100, "revenue": 72000},
    }
    s = db.get(state.upper(), {"users": 0, "revenue": 0})
    return f"Active Users: {s['users']}, Total Revenue: ${s['revenue']}"


class Tracer:
    def __init__(self, prompt: str):
        self.prompt = prompt
        self.steps = []

    def log(self, name, step_type, input_val, output_val, pt=0, ct=0, cost=0.0):
        self.steps.append({
            "step_id": f"step-{len(self.steps) + 1}",
            "step_index": len(self.steps) + 1,
            "step_type": step_type,
            "name": name,
            "input_payload": {"query": str(input_val)},
            "output_payload": {"result": str(output_val)},
            "status": "success",
            "tokens": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct, "estimated_cost_usd": cost},
        })

    def trace(self, trace_id):
        return {
            "trace_id": trace_id,
            "agent_name": "gemini_support_agent",
            "task_input": {"query": self.prompt},
            "steps": self.steps,
            "total_tokens": {
                "prompt_tokens": sum(s["tokens"]["prompt_tokens"] for s in self.steps),
                "completion_tokens": sum(s["tokens"]["completion_tokens"] for s in self.steps),
                "total_tokens": sum(s["tokens"]["total_tokens"] for s in self.steps),
                "estimated_cost_usd": sum(s["tokens"]["estimated_cost_usd"] for s in self.steps),
            },
        }


def run_agent(prompt: str, trace_id: str) -> dict:
    if not os.environ.get("GEMINI_API_KEY"):
        print("[Error] GEMINI_API_KEY not set"); sys.exit(1)
    client = genai.Client()
    tracer = Tracer(prompt)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    for turn in range(5):
        resp = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                tools=[get_user_database_stats],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                ),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                temperature=0.0,
            ),
        )
        usage = resp.usage_metadata
        pt = usage.prompt_token_count
        ct = usage.candidates_token_count
        cost = (pt + ct) * COST_PER_TOKEN
        if resp.function_calls:
            tracer.log("gemini_tool_decision", "routing", str(contents[-1]),
                       f"Suggested: {resp.function_calls[0].name}", pt, ct, cost)
        else:
            tracer.log("gemini_synthesis", "llm_call", str(contents[-1]), resp.text, pt, ct, cost)
        contents.append(resp.candidates[0].content)
        if not resp.function_calls:
            break
        for fc in resp.function_calls:
            result = get_user_database_stats(state=fc.args.get("state", "NY"))
            tracer.log("get_user_database_stats", "tool_call",
                       f"state={fc.args.get('state')}", result, 0, 0, 0.0)
            contents.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=fc.name, response={"result": result})]))
    return tracer.trace(trace_id)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prompt", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--trace-id", default="run")
    args = p.parse_args()
    trace = run_agent(args.prompt, args.trace_id)
    with open(args.out, "w") as f:
        json.dump(trace, f, indent=2)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()