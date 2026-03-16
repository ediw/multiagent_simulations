from __future__ import annotations

import json
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from tqdm import tqdm

from models import SimulationConfig
from simulator import MultiAgentMailSimulator
from factory import make_default_agents, make_default_graph
from graph import AgentGraph  # noqa: F401
from models import (  # noqa: F401
    Agent,
    AgentType,
    Case,
    CaseStatus,
    EdgeState,
    Event,
    EventType,
    Subtask,
    SubtaskStatus,
    TimeseriesSnapshot,
)
from metrics import MetricsCollector  # noqa: F401
from policies import Policies  # noqa: F401


# ============================================================
# CONFIG LOADER
# ============================================================

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def load_config(path: os.PathLike | str | None = None) -> SimulationConfig:
    """Load SimulationConfig from a YAML file.

    Extra keys not present in SimulationConfig (e.g. monte_carlo_runs)
    are silently ignored so the YAML can carry experiment-level settings.
    """
    path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as fh:
        raw: Dict[str, Any] = yaml.safe_load(fh) or {}
    valid_fields = {f.name for f in SimulationConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in raw.items() if k in valid_fields}
    # Resolve fleet_config path relative to the config YAML directory
    if filtered.get("fleet_config"):
        filtered["fleet_config"] = str(path.parent / filtered["fleet_config"])
    return SimulationConfig(**filtered)


# ============================================================
# EXPERIENCE STATE PERSISTENCE
# ============================================================


def save_experience_state(
    agents: Dict[str, "Agent"],
    graph: "AgentGraph",
    path: os.PathLike | str,
    *,
    runs_completed: int = 0,
    decay: float = 1.0,
) -> None:
    """Serialize agent experience + edge trust to a JSON file."""
    agent_state: Dict[str, Any] = {}
    for aid, a in agents.items():
        agent_state[aid] = {
            "neighbor_trust_scores": a.neighbor_trust_scores,
            "local_success_memory": a.local_success_memory,
            "local_failure_memory": a.local_failure_memory,
        }

    state = {
        "agents": agent_state,
        "edge_trust": graph.snapshot_trust(),
        "metadata": {
            "runs_completed": runs_completed,
            "decay": decay,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    Path(path).write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def load_experience_state(
    agents: Dict[str, "Agent"],
    graph: "AgentGraph",
    path: os.PathLike | str,
) -> Dict[str, Any]:
    """Load previously saved experience into *agents* and *graph*.

    Returns the metadata dict from the saved file.
    Only agents / edges present in both the save-file and the current
    topology are restored; others are silently skipped.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    for aid, saved in raw.get("agents", {}).items():
        if aid not in agents:
            continue
        a = agents[aid]
        a.neighbor_trust_scores.update(saved.get("neighbor_trust_scores", {}))
        a.local_success_memory.update(saved.get("local_success_memory", {}))
        a.local_failure_memory.update(saved.get("local_failure_memory", {}))

    for edge_key, trust_val in raw.get("edge_trust", {}).items():
        src, dst = edge_key.split("->")
        if graph.has_edge(src, dst):
            graph._g[src][dst]["state"].historical_success = trust_val

    return raw.get("metadata", {})


# ============================================================
# EXPERIMENTS
# ============================================================


def run_single_experiment(
    config: Optional[SimulationConfig] = None,
    return_sim: bool = False,
) -> "Dict[str, float] | Tuple[Dict[str, float], MultiAgentMailSimulator]":
    config = config or SimulationConfig()
    agents = make_default_agents(seed=config.seed, fleet_path=config.fleet_config)
    graph = make_default_graph(agents, seed=config.seed, intra_group_density=config.intra_group_density, fleet_path=config.fleet_config)
    sim = MultiAgentMailSimulator(config=config, agents=agents, graph=graph)
    summary = sim.run()
    if return_sim:
        return summary, sim
    return summary


def run_monte_carlo(
    n_runs: int = 10,
    base_config: Optional[SimulationConfig] = None,
    return_sims: bool = False,
) -> "Dict[str, float] | Tuple[Dict[str, float], List[MultiAgentMailSimulator]]":
    base_config = base_config or SimulationConfig()
    results: List[Dict[str, float]] = []
    sims: List[MultiAgentMailSimulator] = []
    for run_idx in tqdm(range(n_runs), desc="Cold-start MC", unit="run"):
        cfg = SimulationConfig(**{**base_config.__dict__, "seed": base_config.seed + run_idx})
        summary, sim = run_single_experiment(cfg, return_sim=True)
        results.append(summary)
        sims.append(sim)

    keys = sorted(results[0].keys()) if results else []
    aggregated: Dict[str, float] = {}
    for key in keys:
        vals = [r[key] for r in results]
        aggregated[f"{key}_mean"] = statistics.mean(vals)
        aggregated[f"{key}_std"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    if return_sims:
        return aggregated, sims
    return aggregated


# ============================================================
# WARM-START MONTE CARLO
# ============================================================


def _reset_agents_for_warm_start(agents: Dict[str, Agent], decay: float) -> None:
    """Reset operational state but preserve (decayed) experience."""
    for agent in agents.values():
        agent.queue.clear()
        agent.active_item = None
        agent.current_load = 0.0
        agent.fatigue_level = 0.0
        agent.busy_until = 0.0
        for neighbor_id in agent.neighbor_trust_scores:
            old = agent.neighbor_trust_scores[neighbor_id]
            agent.neighbor_trust_scores[neighbor_id] = 0.5 + decay * (old - 0.5)


def run_warm_monte_carlo(
    n_runs: int = 10,
    base_config: Optional[SimulationConfig] = None,
    return_sims: bool = False,
    *,
    load_experience_path: Optional[str] = None,
    save_experience_path: Optional[str] = None,
) -> "Dict[str, object] | Tuple[Dict[str, object], List[MultiAgentMailSimulator]]":
    base_config = base_config or SimulationConfig()
    decay = base_config.trust_decay

    agents = make_default_agents(seed=base_config.seed, fleet_path=base_config.fleet_config)
    graph = make_default_graph(agents, seed=base_config.seed, intra_group_density=base_config.intra_group_density, fleet_path=base_config.fleet_config)

    # Optionally bootstrap from a previously saved experience state
    if load_experience_path and Path(load_experience_path).exists():
        meta = load_experience_state(agents, graph, load_experience_path)
        print(f"  Loaded experience from {load_experience_path} "
              f"(runs_completed={meta.get('runs_completed')}, "
              f"saved={meta.get('timestamp', '?')})")

    per_run_results: List[Dict[str, float]] = []
    sims: List[MultiAgentMailSimulator] = []

    for run_idx in tqdm(range(n_runs), desc="Warm-start MC", unit="run"):
        cfg = SimulationConfig(**{**base_config.__dict__, "seed": base_config.seed + run_idx})

        if run_idx > 0:
            _reset_agents_for_warm_start(agents, decay)
            graph.decay_trust(decay)

        sim = MultiAgentMailSimulator(config=cfg, agents=agents, graph=graph)
        result = sim.run()
        per_run_results.append(result)
        sims.append(sim)

    # Optionally persist the final experience state
    if save_experience_path:
        save_experience_state(
            agents, graph, save_experience_path,
            runs_completed=n_runs, decay=decay,
        )
        print(f"  Experience saved to {save_experience_path}")

    keys = sorted(per_run_results[0].keys()) if per_run_results else []
    aggregated: Dict[str, float] = {}
    for key in keys:
        vals = [r[key] for r in per_run_results]
        aggregated[f"{key}_mean"] = statistics.mean(vals)
        aggregated[f"{key}_std"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0

    result_dict: Dict[str, object] = {
        "aggregated": aggregated,
        "per_run": per_run_results,
    }
    if return_sims:
        return result_dict, sims
    return result_dict


# ============================================================
# MAIN
# ============================================================


if __name__ == "__main__":
    import sys

    cfg_path = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(cfg_path)

    # Read experiment-level settings from raw YAML
    with open(cfg_path or _DEFAULT_CONFIG_PATH, encoding="utf-8") as _fh:
        _raw = yaml.safe_load(_fh) or {}
    mc_runs: int = int(_raw.get("monte_carlo_runs", 5))
    warm_mc_runs: int = int(_raw.get("warm_monte_carlo_runs", mc_runs))
    experience_path: Optional[str] = _raw.get("experience_state_path")

    # Single run
    result = run_single_experiment(config)
    print("Single run summary:")
    for k, v in result.items():
        print(f"  {k}: {v:.4f}")

    # Cold-start Monte Carlo
    print(f"\nCold-start Monte Carlo ({mc_runs} runs):")
    mc_cold = run_monte_carlo(n_runs=mc_runs, base_config=config)
    for k, v in mc_cold.items():
        print(f"  {k}: {v:.4f}")

    # Warm-start Monte Carlo
    print(f"\nWarm-start Monte Carlo ({warm_mc_runs} runs, decay={config.trust_decay}):")
    mc_warm = run_warm_monte_carlo(
        n_runs=warm_mc_runs,
        base_config=config,
        load_experience_path=experience_path,
        save_experience_path=experience_path,
    )
    for k, v in mc_warm["aggregated"].items():
        print(f"  {k}: {v:.4f}")

    # Per-run trend
    print("\nWarm-start per-run trend:")
    for i, run_result in enumerate(mc_warm["per_run"]):
        print(f"  Run {i+1}: closed={run_result['closed_cases']:.0f}  "
              f"avg_q={run_result['avg_quality']:.3f}  "
              f"lead={run_result['mean_lead_time']:.1f}  "
              f"esc={run_result['escalation_rate']:.3f}  "
              f"entropy={run_result['routing_entropy']:.3f}")
