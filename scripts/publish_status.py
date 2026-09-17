# /// script
# requires-python = ">=3.10"
# dependencies = ["agent-trajectory-diff"]
# ///
"""Publish a machine-readable gate status for the live demo.

Runs the real statistical gate in-process (library API, not the CLI) and emits:

    status/latest.json    — full verdict, metrics, envelope bands, findings
    status/history.json   — rolling compact history (default: last 60 runs)

This file powers the public live scoreboard. It is deliberately non-fatal:
if anything is missing (no candidate trace, no baseline), it publishes an
explicit ``error`` status instead of failing CI, so the scoreboard never goes
silent and the gate step above keeps ownership of pass/fail semantics.

Usage:
    python scripts/publish_status.py \
        --baseline baselines/default.envelope.json \
        --candidate traces/candidate.json \
        --config agentdiff.toml --scenario default \
        --out-dir status --history-limit 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0.0"
KIND = "agentdiff_gate_status"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def context() -> dict[str, str | None]:
    """CI context, or local fallbacks when run outside GitHub Actions."""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None
    return {
        "repository": repo,
        "commit": (os.environ.get("GITHUB_SHA") or "")[:12] or None,
        "run_id": run_id,
        "run_url": run_url,
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "workflow": os.environ.get("GITHUB_WORKFLOW"),
    }


def write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def band_view(band) -> dict[str, float]:
    return {"mean": round(band.mean, 4), "std_dev": round(band.std_dev, 4)}


def build_status(baseline_path: Path, candidate_path: Path, config_path: Path, scenario_name: str) -> dict:
    """Computes the status payload. Never raises — errors land in the payload."""
    import agentdiff
    from agentdiff.config import load_config
    from agentdiff.engine.comparator import compare_envelope
    from agentdiff.governance import provenance_line
    from agentdiff.loader import load_baseline, load_trace

    status: dict = {
        "schema_version": SCHEMA_VERSION,
        "package_version": getattr(agentdiff, "__version__", None),
        "kind": KIND,
        "generated_at": now_iso(),
        "scenario": scenario_name,
        "context": context(),
    }

    try:
        if not baseline_path.exists():
            raise FileNotFoundError(f"baseline not found: {baseline_path}")
        if not candidate_path.exists():
            raise FileNotFoundError(f"candidate not found: {candidate_path}")

        envelope = load_baseline(str(baseline_path))
        candidate = load_trace(str(candidate_path))

        cfg = load_config(str(config_path)) if config_path.exists() else None
        scenario = cfg.scenario(scenario_name) if cfg else None
        tolerances = getattr(scenario, "tolerances", None)
        max_divergence = tolerances.divergence_ceiling if tolerances else 0.35
        step_count_std_dev = tolerances.step_count_std_dev if tolerances else 2.0
        max_cost_increase_pct = scenario.max_cost_increase_pct if scenario else 20.0
        hard = getattr(scenario, "hard_invariants", None)
        fail_on_identical_loops = bool(getattr(hard, "fail_on_identical_loops", True))
        max_tool_repeats = getattr(hard, "max_tool_repeats", None)

        report, gate = compare_envelope(
            envelope,
            candidate,
            max_divergence=max_divergence,
            max_cost_increase_pct=max_cost_increase_pct,
            step_count_std_dev=step_count_std_dev,
            fail_on_identical_loops=fail_on_identical_loops,
            max_tool_repeats=max_tool_repeats,
        )

        failing = [f.code for f in gate.violations]
        status["baseline"] = {
            "mode": envelope.mode,
            "n_runs": envelope.n_runs,
            "recorded_at": envelope.recorded_at,
            "schema_version": envelope.schema_version,
            "bands": {name: band_view(band) for name, band in envelope.envelope.items()},
        }
        status["candidate"] = {
            "trace_id": candidate.trace_id,
            "agent_name": candidate.agent_name,
            "steps": len(candidate.steps),
            "total_tokens": candidate.total_tokens.total_tokens,
            "estimated_cost_usd": round(candidate.total_tokens.estimated_cost_usd, 6),
            "latency_ms": round(candidate.total_latency_ms, 1),
        }
        status["verdict"] = {
            "passed": bool(gate.passed),
            "status": "PASSED" if gate.passed else "BLOCKED",
            "headline": (
                "No loops. Cost within band. Trajectory within budget."
                if gate.passed
                else "Blocked by: " + ", ".join(failing or ["regression"])
            ),
        }
        status["metrics"] = {
            "trajectory_divergence_index": round(report.trajectory_divergence_index, 4),
            "loops_detected": len(report.loops_detected),
            "identical_call_loops": len(report.identical_call_loops),
            "wasted_effort": {
                "baseline": round(report.baseline_wei, 4),
                "candidate": round(report.candidate_wei, 4),
            },
            "recovery_step_ratio": round(report.recovery_step_ratio, 3),
            "token_delta_pct": round(report.token_delta_percentage, 2),
            "cost_delta_pct": round(report.cost_delta_percentage, 2),
            "latency_delta_pct": round(report.latency_delta_percentage, 2),
            "tool_call_counts": report.tool_call_counts,
        }
        status["thresholds"] = {
            "divergence_ceiling": max_divergence,
            "step_count_std_dev": step_count_std_dev,
            "max_cost_increase_pct": max_cost_increase_pct,
            "fail_on_identical_loops": fail_on_identical_loops,
            "max_tool_repeats": max_tool_repeats,
        }
        status["findings"] = [
            {"severity": f.severity.value, "code": f.code, "message": f.message}
            for f in list(gate.violations) + list(gate.warnings)
        ]
        status["provenance"] = provenance_line(
            cfg, str(config_path) if config_path.exists() else None,
            scenario_cfg=scenario, envelope=envelope,
        )
        status["gate_exit_code"] = 1 if not gate.passed else 0
    except Exception as exc:  # noqa: BLE001 — status must always publish
        status["error"] = {"type": type(exc).__name__, "message": str(exc)}
        status["verdict"] = {"passed": None, "status": "UNKNOWN", "headline": "Gate status unavailable"}
        status["gate_exit_code"] = None

    return status


def history_entry(status: dict) -> dict:
    metrics = status.get("metrics", {})
    candidate = status.get("candidate", {})
    findings = status.get("findings") or []
    return {
        "at": status.get("generated_at"),
        "engine": status.get("package_version"),
        "headline": (status.get("verdict") or {}).get("headline"),
        "codes": [f.get("code") for f in findings],
        "passed": (status.get("verdict") or {}).get("passed"),
        "status": (status.get("verdict") or {}).get("status"),
        "tdi": metrics.get("trajectory_divergence_index"),
        "loops": metrics.get("loops_detected"),
        "token_delta_pct": metrics.get("token_delta_pct"),
        "cost_delta_pct": metrics.get("cost_delta_pct"),
        "steps": candidate.get("steps"),
        "tokens": candidate.get("total_tokens"),
        "run_url": (status.get("context") or {}).get("run_url"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="baselines/default.envelope.json")
    parser.add_argument("--candidate", default="traces/candidate.json")
    parser.add_argument("--config", default="agentdiff.toml")
    parser.add_argument("--scenario", default="default")
    parser.add_argument("--out-dir", default="status")
    parser.add_argument("--history-limit", type=int, default=60)
    args = parser.parse_args()

    status = build_status(Path(args.baseline), Path(args.candidate), Path(args.config), args.scenario)

    out_dir = Path(args.out_dir)
    write_json_atomic(out_dir / "latest.json", status)

    history_path = out_dir / "history.json"
    history: list[dict] = []
    if history_path.exists():
        try:
            loaded = json.loads(history_path.read_text(encoding="utf-8"))
            history = loaded.get("runs", []) if isinstance(loaded, dict) else []
        except json.JSONDecodeError:
            history = []
    history = (history + [history_entry(status)])[-args.history_limit:]
    write_json_atomic(
        history_path,
        {
            "schema_version": SCHEMA_VERSION,
            "kind": "agentdiff_gate_history",
            "updated_at": status.get("generated_at"),
            "runs": history,
        },
    )

    verdict = (status.get("verdict") or {}).get("status", "UNKNOWN")
    print(f"status published: {verdict} -> {out_dir / 'latest.json'} ({len(history)} run(s) in history)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
