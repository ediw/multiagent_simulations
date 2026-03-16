"""Export raw simulation data to JSON files inside ``output/data/``.

The exported data is 1-to-1 with what the visualization charts consume,
so any external analysis will operate on the exact same numbers.

Usage::

    from export import export_single_run, export_monte_carlo_cold, export_warm_start

    export_single_run(sim)
    export_monte_carlo_cold(mc_sims)
    export_warm_start(per_run, cold_sims, decay)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from models import CaseStatus
from simulator import MultiAgentMailSimulator

_BASE_OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def _data_dir(output_dir: str) -> str:
    return os.path.join(output_dir, "data")


def _write_json(name: str, payload: Any, output_dir: str) -> None:
    data = _data_dir(output_dir)
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
    print(f"  exported {path}")


# ====================================================================
# 1. Single run  (charts 01–08, 10, 11)
# ====================================================================

def export_single_run(sim: MultiAgentMailSimulator, output_dir: str = "") -> None:
    """Export all single-run data consumed by charts 01-08, 10, 11."""
    output_dir = output_dir or os.path.join(_BASE_OUTPUT, "default")
    ts = sim.metrics.timeseries
    timestamps = [s.timestamp for s in ts]

    # -- config (chart 02) --
    config_dict = sim.config.__dict__.copy()

    # -- agents (chart 01, 02, 05, 08) --
    agents_export: Dict[str, Any] = {}
    for aid, a in sim.agents.items():
        agents_export[aid] = {
            "agent_type": a.agent_type.value,
            "skills": a.skills,
            "base_accuracy": a.base_accuracy,
            "base_confidence": a.base_confidence,
            "avg_service_time": a.avg_service_time,
            "queue_capacity": a.queue_capacity,
            "cost_per_action": a.cost_per_action,
            "split_propensity": a.split_propensity,
            "escalation_threshold": a.escalation_threshold,
            "rework_threshold": a.rework_threshold,
            "fatigue_increase": a.fatigue_increase,
            "fatigue_recovery": a.fatigue_recovery,
        }

    # -- edges / trust (chart 01, 06) --
    initial_trust = sim.initial_graph_snapshot
    final_trust = sim.graph.snapshot_trust()
    edges_export: List[Dict[str, Any]] = []
    for src, neighbors in sim.graph.all_edges().items():
        for dst, es in neighbors.items():
            key = f"{src}->{dst}"
            edges_export.append({
                "src": src,
                "dst": dst,
                "base_transfer_cost": es.base_transfer_cost,
                "latency": es.latency,
                "initial_trust": initial_trust.get(key, 0.5),
                "final_trust": final_trust.get(key, es.historical_success),
            })

    # -- routing counts (chart 01, 07) --
    routing_counts = sim.metrics.routing_counts

    # -- timeseries (charts 03, 04, 05, 06, 10, 11) --
    timeseries_export: List[Dict[str, Any]] = []
    for s in ts:
        timeseries_export.append({
            "timestamp": s.timestamp,
            "queue_lengths": s.queue_lengths,
            "queue_lengths_by_type": s.queue_lengths_by_type,
            "fatigue_levels": s.fatigue_levels,
            "cumulative_open": s.cumulative_open,
            "cumulative_closed": s.cumulative_closed,
            "cumulative_escalated": s.cumulative_escalated,
            "trust_scores": s.trust_scores,
            "effective_temperature": s.effective_temperature,
            "effective_internal_energy": s.effective_internal_energy,
            "effective_entropy": s.effective_entropy,
            "effective_free_energy": s.effective_free_energy,
            "sla_at_risk_count": s.sla_at_risk_count,
            "priority_distribution": s.priority_distribution,
            "cumulative_timeout_requeues": s.cumulative_timeout_requeues,
        })

    # -- metrics summary (chart 08) --
    summary = sim.metrics.summary()

    # -- distributions (chart 08) --
    lead_times = sim.metrics.lead_times
    quality_scores = sim.metrics.quality_scores
    agent_busy_time = sim.metrics.agent_busy_time
    queue_samples = {
        aid: samples for aid, samples in sim.metrics.queue_samples.items()
    }

    # -- SLA breach timeline (chart 11) --
    sla_breaches_timeline: List[Dict[str, Any]] = []
    for t in timestamps:
        count = sum(
            1 for c in sim.cases.values()
            if c.status == CaseStatus.CLOSED
            and c.close_time is not None
            and c.close_time <= t
            and c.close_time > c.deadline
        )
        sla_breaches_timeline.append({"timestamp": t, "cumulative_breaches": count})

    payload = {
        "config": config_dict,
        "agents": agents_export,
        "edges": edges_export,
        "routing_counts": routing_counts,
        "timeseries": timeseries_export,
        "summary": summary,
        "lead_times": lead_times,
        "quality_scores": quality_scores,
        "agent_busy_time": agent_busy_time,
        "queue_samples": queue_samples,
        "sla_breaches_timeline": sla_breaches_timeline,
    }
    _write_json("simulation_data", payload, output_dir)


# ====================================================================
# 2. Cold-start Monte Carlo  (chart 09)
# ====================================================================

def export_monte_carlo_cold(sims: List[MultiAgentMailSimulator], output_dir: str = "") -> None:
    """Export per-run summaries for cold-start MC (chart 09)."""
    output_dir = output_dir or os.path.join(_BASE_OUTPUT, "default")
    per_run = [s.metrics.summary() for s in sims]
    payload = {
        "n_runs": len(sims),
        "per_run": per_run,
    }
    _write_json("monte_carlo_cold", payload, output_dir)


# ====================================================================
# 3. Warm-start trend  (chart 12)
# ====================================================================

def export_warm_start(
    per_run: List[Dict[str, float]],
    cold_sims: Optional[List[MultiAgentMailSimulator]] = None,
    decay: float = 0.9,
    output_dir: str = "",
) -> None:
    """Export warm-start per-run results + cold baseline (chart 12)."""
    output_dir = output_dir or os.path.join(_BASE_OUTPUT, "default")
    cold_summaries = [s.metrics.summary() for s in cold_sims] if cold_sims else []
    payload = {
        "decay": decay,
        "n_warm_runs": len(per_run),
        "warm_per_run": per_run,
        "n_cold_runs": len(cold_summaries),
        "cold_per_run": cold_summaries,
    }
    _write_json("warm_start_trend", payload, output_dir)


# ====================================================================
# Convenience: export everything at once
# ====================================================================

def export_all(
    sim: MultiAgentMailSimulator,
    mc_sims: Optional[List[MultiAgentMailSimulator]] = None,
    warm_per_run: Optional[List[Dict[str, float]]] = None,
    warm_decay: float = 0.9,
    output_dir: str = "",
) -> None:
    """Export all simulation data that feeds into the visualization charts."""
    output_dir = output_dir or os.path.join(_BASE_OUTPUT, "default")
    print("Exporting raw data …")
    export_single_run(sim, output_dir=output_dir)
    if mc_sims:
        export_monte_carlo_cold(mc_sims, output_dir=output_dir)
    if warm_per_run is not None:
        export_warm_start(warm_per_run, cold_sims=mc_sims, decay=warm_decay, output_dir=output_dir)
    print("Export done.")
