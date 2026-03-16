from __future__ import annotations

import os
import random
from typing import Any, Dict, List, Optional, Tuple

import yaml

from models import Agent, AgentType
from graph import AgentGraph


# ============================================================
# HELPERS
# ============================================================

def _rv(rnd: random.Random, spec: Any) -> float:
    """Resolve a value spec: [min, max] → uniform, scalar → as-is."""
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        return rnd.uniform(float(spec[0]), float(spec[1]))
    return float(spec)


def _load_fleet(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ============================================================
# FLEET-DRIVEN FACTORY
# ============================================================

def _make_agents_from_fleet(fleet: Dict[str, Any], seed: int) -> Dict[str, Agent]:
    rnd = random.Random(seed)
    agents: Dict[str, Agent] = {}
    defaults = fleet.get("agent_defaults", {})

    for group in fleet.get("agents", []):
        prefix = group["prefix"]
        agent_type = AgentType(group["type"])
        count = int(group.get("count", 1))

        for i in range(1, count + 1):
            aid = f"{prefix}-{i}"
            skills = {k: _rv(rnd, v) for k, v in group.get("skills", {}).items()}

            agents[aid] = Agent(
                agent_id=aid,
                agent_type=agent_type,
                skills=skills,
                base_accuracy=_rv(rnd, group.get("base_accuracy", defaults.get("base_accuracy", 0.85))),
                base_confidence=_rv(rnd, group.get("base_confidence", defaults.get("base_confidence", 0.70))),
                avg_service_time=_rv(rnd, group.get("avg_service_time", 5.0)),
                queue_capacity=int(group.get("queue_capacity", 8)),
                cost_per_action=_rv(rnd, group.get("cost_per_action", defaults.get("cost_per_action", 1.5))),
                split_propensity=_rv(rnd, group.get("split_propensity", defaults.get("split_propensity", 0.45))),
                escalation_threshold=_rv(rnd, group.get("escalation_threshold", defaults.get("escalation_threshold", 0.25))),
                rework_threshold=_rv(rnd, group.get("rework_threshold", defaults.get("rework_threshold", 0.60))),
                fatigue_increase=_rv(rnd, group.get("fatigue_increase", defaults.get("fatigue_increase", 0.02))),
                fatigue_recovery=_rv(rnd, group.get("fatigue_recovery", defaults.get("fatigue_recovery", 0.01))),
            )

    # Per-agent overrides
    _OVERRIDE_FIELDS = (
        "base_accuracy", "base_confidence", "avg_service_time",
        "cost_per_action", "split_propensity", "escalation_threshold",
        "rework_threshold", "fatigue_increase", "fatigue_recovery",
    )
    for aid, ovr in fleet.get("overrides", {}).items():
        if aid not in agents:
            continue
        a = agents[aid]
        if "skills" in ovr:
            for sk, sv in ovr["skills"].items():
                a.skills[sk] = _rv(rnd, sv)
        if "queue_capacity" in ovr:
            a.queue_capacity = int(ovr["queue_capacity"])
        for field in _OVERRIDE_FIELDS:
            if field in ovr:
                setattr(a, field, _rv(rnd, ovr[field]))

    # Initialize default trust
    for src in agents.values():
        for dst in agents.values():
            if src.agent_id != dst.agent_id:
                src.neighbor_trust_scores[dst.agent_id] = 0.5

    return agents


def _make_graph_from_fleet(
    fleet: Dict[str, Any],
    agents: Dict[str, Agent],
    seed: int,
    fallback_density: float,
) -> AgentGraph:
    rnd = random.Random(seed)
    graph = AgentGraph()
    for agent_id in agents:
        graph.add_agent(agent_id)

    topo = fleet.get("topology", {})
    density = topo.get("intra_group_density", fallback_density)
    intra_cost = topo.get("intra_group_cost", [0.6, 1.1])
    intra_latency = topo.get("intra_group_latency", [0.1, 0.4])

    grouped: Dict[str, List[str]] = {}
    for a in agents.values():
        grouped.setdefault(a.agent_type.value, []).append(a.agent_id)

    # Intra-group edges
    for group_ids in grouped.values():
        for i, src in enumerate(group_ids):
            for dst in group_ids[i + 1:]:
                if rnd.random() < density:
                    graph.add_edge(
                        src, dst,
                        base_transfer_cost=_rv(rnd, intra_cost),
                        latency=_rv(rnd, intra_latency),
                    )

    # Inter-group edges
    for link in topo.get("inter_group", []):
        src_type = link["src"]
        dst_type = link["dst"]
        link_density = link.get("density", 0.5)
        link_cost = link.get("cost", [0.6, 1.2])
        link_latency = link.get("latency", [0.2, 0.5])
        for src in grouped.get(src_type, []):
            for dst in grouped.get(dst_type, []):
                if rnd.random() < link_density:
                    graph.add_edge(
                        src, dst,
                        base_transfer_cost=_rv(rnd, link_cost),
                        latency=_rv(rnd, link_latency),
                    )

    return graph


# ============================================================
# HARDCODED FALLBACK (original logic)
# ============================================================

def _make_hardcoded_agents(seed: int) -> Dict[str, Agent]:
    rnd = random.Random(seed)
    agents: Dict[str, Agent] = {}

    def create(agent_id: str, agent_type: AgentType, skills: Dict[str, float], avg_service_time: float, queue_capacity: int) -> None:
        agents[agent_id] = Agent(
            agent_id=agent_id,
            agent_type=agent_type,
            skills=skills,
            base_accuracy=rnd.uniform(0.75, 0.93),
            base_confidence=rnd.uniform(0.55, 0.85),
            avg_service_time=avg_service_time,
            queue_capacity=queue_capacity,
            cost_per_action=rnd.uniform(0.8, 2.6),
            split_propensity=rnd.uniform(0.15, 0.75),
            escalation_threshold=rnd.uniform(0.18, 0.35),
            rework_threshold=rnd.uniform(0.50, 0.68),
        )

    for i in range(1, 7):
        create(
            f"INT-{i}",
            AgentType.INTAKE,
            {"mail_understanding": rnd.uniform(0.60, 0.85), "validation": rnd.uniform(0.25, 0.45)},
            avg_service_time=rnd.uniform(2.0, 4.0),
            queue_capacity=10,
        )
    for i in range(1, 9):
        create(
            f"CTX-{i}",
            AgentType.CONTEXT,
            {"mail_understanding": rnd.uniform(0.70, 0.95), "merge_resolution": rnd.uniform(0.30, 0.55)},
            avg_service_time=rnd.uniform(3.0, 6.0),
            queue_capacity=8,
        )
    for i in range(1, 9):
        create(
            f"EXT-{i}",
            AgentType.EXTRACTION,
            {"attachment_extraction": rnd.uniform(0.65, 0.95), "validation": rnd.uniform(0.20, 0.40)},
            avg_service_time=rnd.uniform(4.0, 8.0),
            queue_capacity=8,
        )
    for i in range(1, 7):
        create(
            f"VAL-{i}",
            AgentType.VALIDATION,
            {"validation": rnd.uniform(0.70, 0.95), "merge_resolution": rnd.uniform(0.25, 0.45)},
            avg_service_time=rnd.uniform(2.5, 5.0),
            queue_capacity=8,
        )
    for i in range(1, 5):
        create(
            f"RES-{i}",
            AgentType.RESOLVER,
            {"merge_resolution": rnd.uniform(0.72, 0.95), "validation": rnd.uniform(0.40, 0.60)},
            avg_service_time=rnd.uniform(3.0, 6.0),
            queue_capacity=6,
        )
    for i in range(1, 3):
        create(
            f"HUM-{i}",
            AgentType.HUMAN,
            {"merge_resolution": 0.99, "validation": 0.99, "mail_understanding": 0.99, "attachment_extraction": 0.99},
            avg_service_time=rnd.uniform(10.0, 15.0),
            queue_capacity=20,
        )
    for i in range(1, 3):
        create(
            f"MEM-{i}",
            AgentType.MEMORY,
            {"case_memory": rnd.uniform(0.80, 0.95), "pattern_lookup": rnd.uniform(0.75, 0.90)},
            avg_service_time=rnd.uniform(1.5, 3.0),
            queue_capacity=12,
        )

    # Initialize default trust
    for src in agents.values():
        for dst in agents.values():
            if src.agent_id != dst.agent_id:
                src.neighbor_trust_scores[dst.agent_id] = 0.5

    return agents


def _make_hardcoded_graph(agents: Dict[str, Agent], seed: int, intra_group_density: float) -> AgentGraph:
    rnd = random.Random(seed)
    graph = AgentGraph()
    for agent_id in agents:
        graph.add_agent(agent_id)

    grouped: Dict[AgentType, List[str]] = {}
    for a in agents.values():
        grouped.setdefault(a.agent_type, []).append(a.agent_id)

    # Sparse intra-group links (controlled by density)
    for group_ids in grouped.values():
        for i, src in enumerate(group_ids):
            for dst in group_ids[i + 1:]:
                if rnd.random() < intra_group_density:
                    graph.add_edge(src, dst, base_transfer_cost=rnd.uniform(0.6, 1.1), latency=rnd.uniform(0.1, 0.4))

    # Structured inter-group links
    def connect_groups(g1: AgentType, g2: AgentType, density: float, cost: Tuple[float, float], latency: Tuple[float, float]) -> None:
        for src in grouped.get(g1, []):
            for dst in grouped.get(g2, []):
                if rnd.random() < density:
                    graph.add_edge(src, dst, base_transfer_cost=rnd.uniform(*cost), latency=rnd.uniform(*latency))

    connect_groups(AgentType.INTAKE, AgentType.CONTEXT, 0.65, (0.7, 1.2), (0.2, 0.5))
    connect_groups(AgentType.INTAKE, AgentType.EXTRACTION, 0.45, (0.9, 1.4), (0.3, 0.6))
    connect_groups(AgentType.CONTEXT, AgentType.EXTRACTION, 0.55, (0.7, 1.2), (0.2, 0.5))
    connect_groups(AgentType.CONTEXT, AgentType.VALIDATION, 0.50, (0.8, 1.3), (0.2, 0.5))
    connect_groups(AgentType.EXTRACTION, AgentType.VALIDATION, 0.70, (0.6, 1.0), (0.2, 0.4))
    connect_groups(AgentType.VALIDATION, AgentType.RESOLVER, 0.75, (0.6, 1.0), (0.2, 0.4))
    connect_groups(AgentType.RESOLVER, AgentType.HUMAN, 0.90, (0.5, 0.9), (0.1, 0.3))
    connect_groups(AgentType.INTAKE, AgentType.RESOLVER, 0.20, (1.0, 1.5), (0.3, 0.6))
    connect_groups(AgentType.INTAKE, AgentType.MEMORY, 0.70, (0.4, 0.8), (0.1, 0.3))
    connect_groups(AgentType.CONTEXT, AgentType.MEMORY, 0.70, (0.4, 0.8), (0.1, 0.3))
    connect_groups(AgentType.MEMORY, AgentType.RESOLVER, 0.50, (0.5, 0.9), (0.1, 0.3))

    return graph


# ============================================================
# PUBLIC API (dispatch: fleet YAML → hardcoded fallback)
# ============================================================

def make_default_agents(
    seed: int = 42,
    fleet_path: Optional[str] = None,
) -> Dict[str, Agent]:
    if fleet_path and os.path.exists(fleet_path):
        return _make_agents_from_fleet(_load_fleet(fleet_path), seed)
    return _make_hardcoded_agents(seed)


def make_default_graph(
    agents: Dict[str, Agent],
    seed: int = 42,
    intra_group_density: float = 0.45,
    fleet_path: Optional[str] = None,
) -> AgentGraph:
    if fleet_path and os.path.exists(fleet_path):
        return _make_graph_from_fleet(
            _load_fleet(fleet_path), agents, seed,
            fallback_density=intra_group_density,
        )
    return _make_hardcoded_graph(agents, seed, intra_group_density)
